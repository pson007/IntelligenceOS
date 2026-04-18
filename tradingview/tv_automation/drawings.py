"""Drawings surface — emit Pine indicator that renders a JSON-described
set of chart annotations (horizontal lines, trend lines, boxes, labels,
vertical timestamps).

Why an emitter instead of canvas-coordinate clicks: TradingView's
chart canvas needs (price, time) → (pixel x, y) projection logic that
lives inside TV's React state. Reading it from outside is hairy and
breaks every UI tweak. Pine drawings render natively — `line.new()`
accepts `xloc.bar_time` so timestamps drive positioning directly,
no projection math required. The trade-off: drawings are not
user-draggable post-creation. For LLM-driven annotation that's the
right trade — drawings are recomputable from the JSON, not edited.

CLI:
    tv drawings sketch path/to/sketch.json              # apply a saved sketch
    cat sketch.json | tv drawings sketch --stdin        # apply via stdin
    tv drawings example                                 # print an example sketch JSON
    tv drawings clear                                   # remove the drawings indicator from chart

JSON schema:

    {
      "name": "Resistance levels",          // optional; default "TV Automation Drawings"
      "drawings": [
        {"type": "horizontal", "price": 27000, "color": "blue",
         "width": 1, "style": "dashed", "label": "Resistance"},

        {"type": "trend_line",
         "p1": ["2026-04-15T09:30", 26800.0],
         "p2": ["2026-04-17T15:00", 27200.0],
         "color": "red", "width": 2, "extend": "right"},

        {"type": "box",
         "p1": ["2026-04-15T09:30", 26800.0],
         "p2": ["2026-04-17T15:00", 27200.0],
         "border_color": "green", "bg_color": "green", "bg_alpha": 85},

        {"type": "label",
         "at": ["2026-04-17T12:00", 27000.0],
         "text": "Recent high", "color": "blue", "size": "normal"},

        {"type": "vertical",
         "time": "2026-04-17T15:00",
         "color": "purple", "label": "Pivot"}
      ]
    }

Time formats accepted:
  - ISO 8601 string: "2026-04-15T09:30" or "2026-04-15T09:30:00Z" (UTC assumed if no offset)
  - Integer: Unix epoch seconds

Colors accepted:
  - Named: "red", "blue", "green", "orange", "purple", "yellow",
    "aqua", "fuchsia", "white", "black", "gray", "silver", "lime",
    "maroon", "navy", "olive", "teal"
  - Hex: "#ff0000" → color.rgb(255, 0, 0)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .lib.cli import run

# Default name for the indicator we render. Re-applying with the same
# name overwrites the chart instance, so no clutter accumulates.
DEFAULT_INDICATOR_NAME = "TV Automation Drawings"

# Where we write the generated Pine. /tmp is fine — pine_editor.apply
# reads the file's content and uploads to TV; the local path doesn't
# need to persist.
GENERATED_PATH = Path("/tmp/tv-automation-drawings.pine")

# Named colors map to Pine's `color.X` constants.
_NAMED_COLORS = {
    "red", "blue", "green", "orange", "purple", "yellow", "aqua",
    "fuchsia", "white", "black", "gray", "silver", "lime", "maroon",
    "navy", "olive", "teal",
}

_LINE_STYLES = {
    "solid": "line.style_solid",
    "dashed": "line.style_dashed",
    "dotted": "line.style_dotted",
    "arrow_left": "line.style_arrow_left",
    "arrow_right": "line.style_arrow_right",
    "arrow_both": "line.style_arrow_both",
}

_EXTEND_MODES = {
    "none": "extend.none",
    "left": "extend.left",
    "right": "extend.right",
    "both": "extend.both",
}

_LABEL_SIZES = {
    "auto": "size.auto",
    "tiny": "size.tiny",
    "small": "size.small",
    "normal": "size.normal",
    "large": "size.large",
    "huge": "size.huge",
}

_LABEL_STYLES = {
    "none": "label.style_none",
    "text_outline": "label.style_text_outline",
    "label_up": "label.style_label_up",
    "label_down": "label.style_label_down",
    "arrow_up": "label.style_arrowup",
    "arrow_down": "label.style_arrowdown",
}


# ---------------------------------------------------------------------------
# Coercion helpers — convert spec values to Pine source fragments.
# ---------------------------------------------------------------------------

def _color(value: str | None, default: str = "blue") -> str:
    """Convert a color name or hex string to a Pine color expression."""
    if value is None:
        value = default
    value = value.strip()
    if value.startswith("#"):
        # #rrggbb or #rrggbbaa — Pine has no alpha-in-hex, so we drop
        # alpha and the caller can pass `bg_alpha` explicitly.
        h = value.lstrip("#")
        if len(h) not in (6, 8):
            raise ValueError(f"hex color must be #rrggbb (got {value!r})")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"color.rgb({r}, {g}, {b})"
    name = value.lower()
    if name in _NAMED_COLORS:
        return f"color.{name}"
    raise ValueError(
        f"unknown color {value!r} (use a named color or #rrggbb hex)"
    )


def _color_with_alpha(value: str | None, alpha: int | None,
                      default: str = "blue") -> str:
    """Like _color, but wrapped in color.new() when alpha is set.
    Pine alpha is 0 (opaque) to 100 (transparent) — opposite of CSS,
    keep that in mind."""
    base = _color(value, default)
    if alpha is None:
        return base
    if not (0 <= alpha <= 100):
        raise ValueError(f"alpha must be 0..100 (got {alpha})")
    return f"color.new({base}, {alpha})"


def _pine_time(value: str | int) -> str:
    """Convert a JSON time value to a Pine expression that yields a ms
    timestamp. Acceptable inputs:
      - Integer: treated as Unix epoch seconds.
      - String: ISO 8601 (with or without 'Z' / offset).

    Returned Pine snippet evaluates to a ms timestamp suitable for
    `xloc.bar_time` consumers."""
    if isinstance(value, (int, float)):
        ms = int(value) * 1000
        return str(ms)
    if isinstance(value, str):
        s = value.strip()
        # Accept "Z" suffix.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"can't parse time {value!r}: {e}")
        if dt.tzinfo is None:
            # Assume UTC if no offset.
            dt = dt.replace(tzinfo=timezone.utc)
        ms = int(dt.timestamp() * 1000)
        return str(ms)
    raise TypeError(f"time must be int (epoch sec) or ISO string, got {type(value).__name__}")


def _pine_str(s: str) -> str:
    """Quote a string for Pine source — escapes quotes and backslashes."""
    if s is None:
        return '""'
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _line_style(value: str | None) -> str:
    if value is None:
        return _LINE_STYLES["solid"]
    if value not in _LINE_STYLES:
        raise ValueError(f"unknown line style {value!r}; valid: {sorted(_LINE_STYLES)}")
    return _LINE_STYLES[value]


def _extend(value: str | None) -> str:
    if value is None:
        return _EXTEND_MODES["none"]
    if value not in _EXTEND_MODES:
        raise ValueError(f"unknown extend mode {value!r}; valid: {sorted(_EXTEND_MODES)}")
    return _EXTEND_MODES[value]


def _label_size(value: str | None) -> str:
    if value is None:
        return _LABEL_SIZES["normal"]
    if value not in _LABEL_SIZES:
        raise ValueError(f"unknown label size {value!r}; valid: {sorted(_LABEL_SIZES)}")
    return _LABEL_SIZES[value]


def _label_style(value: str | None) -> str:
    if value is None:
        return _LABEL_STYLES["none"]  # plain text on the chart
    if value not in _LABEL_STYLES:
        raise ValueError(f"unknown label style {value!r}; valid: {sorted(_LABEL_STYLES)}")
    return _LABEL_STYLES[value]


# ---------------------------------------------------------------------------
# Pine emitters — each takes a single drawing spec and returns Pine source
# lines that go inside `if barstate.islast and not _drawn:`.
# ---------------------------------------------------------------------------

def _emit_horizontal(d: dict) -> list[str]:
    """A horizontal line at a fixed price, extending left and right.
    `hline()` is simpler but lives outside conditional blocks; we use
    `line.new()` with `extend.both` for consistency with other emitters."""
    price = d["price"]
    color = _color(d.get("color"), default="blue")
    width = int(d.get("width", 1))
    style = _line_style(d.get("style"))
    out = [
        f"    line.new(x1=bar_index, y1={price}, x2=bar_index + 1, y2={price}, "
        f"extend=extend.both, color={color}, width={width}, style={style})",
    ]
    if d.get("label"):
        out.append(
            f"    label.new(x=bar_index, y={price}, "
            f"text={_pine_str(d['label'])}, color=color.new({color}, 70), "
            f"textcolor=color.white, style=label.style_label_left, "
            f"size=size.small)"
        )
    return out


def _emit_trend_line(d: dict) -> list[str]:
    p1, p2 = d["p1"], d["p2"]
    if not (isinstance(p1, list) and len(p1) == 2):
        raise ValueError("trend_line.p1 must be [time, price]")
    if not (isinstance(p2, list) and len(p2) == 2):
        raise ValueError("trend_line.p2 must be [time, price]")
    t1, y1 = _pine_time(p1[0]), p1[1]
    t2, y2 = _pine_time(p2[0]), p2[1]
    color = _color(d.get("color"), default="orange")
    width = int(d.get("width", 1))
    style = _line_style(d.get("style"))
    extend = _extend(d.get("extend"))
    return [
        f"    line.new(x1={t1}, y1={y1}, x2={t2}, y2={y2}, "
        f"xloc=xloc.bar_time, extend={extend}, "
        f"color={color}, width={width}, style={style})",
    ]


def _emit_box(d: dict) -> list[str]:
    """Box drawing. Accepts any two corners — we sort to satisfy
    Pine's `box.new(top > bottom, right > left)` requirement."""
    p1, p2 = d["p1"], d["p2"]
    if not (isinstance(p1, list) and len(p1) == 2):
        raise ValueError("box.p1 must be [time, price]")
    if not (isinstance(p2, list) and len(p2) == 2):
        raise ValueError("box.p2 must be [time, price]")
    t1, y1 = _pine_time(p1[0]), p1[1]
    t2, y2 = _pine_time(p2[0]), p2[1]
    # Cast to int for time comparison, float for price.
    left, right = sorted([int(t1), int(t2)])
    bottom, top = sorted([float(y1), float(y2)])
    border = _color(d.get("border_color"), default="green")
    bg = _color_with_alpha(
        d.get("bg_color"), d.get("bg_alpha", 85), default="green",
    )
    border_width = int(d.get("border_width", 1))
    out = [
        f"    box.new(left={left}, top={top}, right={right}, bottom={bottom}, "
        f"xloc=xloc.bar_time, border_color={border}, "
        f"border_width={border_width}, bgcolor={bg})",
    ]
    if d.get("label"):
        out.append(
            f"    label.new(x={left}, y={top}, xloc=xloc.bar_time, "
            f"text={_pine_str(d['label'])}, color=color.new({border}, 70), "
            f"textcolor=color.white, style=label.style_label_lower_right, "
            f"size=size.small)"
        )
    return out


def _emit_label(d: dict) -> list[str]:
    at = d["at"]
    if not (isinstance(at, list) and len(at) == 2):
        raise ValueError("label.at must be [time, price]")
    t, y = _pine_time(at[0]), at[1]
    color = _color(d.get("color"), default="blue")
    text = _pine_str(d["text"])
    size = _label_size(d.get("size"))
    style = _label_style(d.get("style"))
    return [
        f"    label.new(x={t}, y={y}, xloc=xloc.bar_time, "
        f"text={text}, color={color}, textcolor=color.white, "
        f"style={style}, size={size})",
    ]


def _emit_vertical(d: dict) -> list[str]:
    """A vertical line at a specific timestamp, extending top to bottom.
    Achieved with line.new + extend.both, anchored at a price that's
    quickly off-screen — the line renders as a vertical."""
    t = _pine_time(d["time"])
    color = _color(d.get("color"), default="purple")
    width = int(d.get("width", 1))
    style = _line_style(d.get("style"))
    out = [
        # Use vline-style: extend both ends vertically. Pine doesn't
        # have a native vertical-line primitive, so we fake it with a
        # very tall line (close[0] - 1e10 to close[0] + 1e10).
        f"    line.new(x1={t}, y1=close - 1e10, x2={t}, y2=close + 1e10, "
        f"xloc=xloc.bar_time, extend=extend.both, color={color}, "
        f"width={width}, style={style})",
    ]
    if d.get("label"):
        out.append(
            f"    label.new(x={t}, y=close, xloc=xloc.bar_time, "
            f"text={_pine_str(d['label'])}, color=color.new({color}, 70), "
            f"textcolor=color.white, style=label.style_label_left, "
            f"size=size.small)"
        )
    return out


_EMITTERS = {
    "horizontal": _emit_horizontal,
    "trend_line": _emit_trend_line,
    "box": _emit_box,
    "label": _emit_label,
    "vertical": _emit_vertical,
}


# ---------------------------------------------------------------------------
# Sketch composer.
# ---------------------------------------------------------------------------

def _validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise ValueError("sketch spec must be a JSON object")
    if "drawings" not in spec:
        raise ValueError("sketch spec must have a 'drawings' array")
    if not isinstance(spec["drawings"], list):
        raise ValueError("'drawings' must be an array")
    for i, d in enumerate(spec["drawings"]):
        if not isinstance(d, dict):
            raise ValueError(f"drawings[{i}] must be an object")
        t = d.get("type")
        if t not in _EMITTERS:
            raise ValueError(
                f"drawings[{i}].type {t!r} not one of {sorted(_EMITTERS)}"
            )


def compose(spec: dict) -> str:
    """Convert a sketch spec into a complete Pine v5 indicator script.

    The generated indicator draws once on the last bar. Re-applying with
    the same name overwrites the chart instance — no clutter accumulates."""
    _validate_spec(spec)
    name = spec.get("name", DEFAULT_INDICATOR_NAME)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")

    body_lines: list[str] = []
    for d in spec["drawings"]:
        emitter = _EMITTERS[d["type"]]
        body_lines.extend(emitter(d))

    # Draw on the last bar with a one-shot guard so we don't redraw on
    # every realtime tick.
    pine = [
        '//@version=5',
        '// Generated by tv_automation.drawings — do not hand-edit.',
        f'indicator({_pine_str(name)}, overlay=true, '
        'max_lines_count=500, max_boxes_count=500, max_labels_count=500)',
        '',
        'var bool _tva_drawn = false',
        '',
        'if barstate.islast and not _tva_drawn',
        '    _tva_drawn := true',
    ]
    if body_lines:
        pine.extend(body_lines)
    else:
        # Empty sketch — emit a no-op so Pine compiles.
        pine.append('    // (no drawings)')
    pine.append('')
    return "\n".join(pine)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def sketch(spec: dict, *, dry_run: bool = False) -> dict:
    """Compose `spec` into Pine, write to /tmp, apply via pine_editor.

    `dry_run=True` emits the Pine to GENERATED_PATH and returns a
    summary without touching the browser. Use to inspect generated
    code before applying."""
    name = spec.get("name", DEFAULT_INDICATOR_NAME)
    pine = compose(spec)
    GENERATED_PATH.write_text(pine)

    if dry_run:
        return {
            "ok": True, "dry_run": True,
            "name": name,
            "drawing_count": len(spec.get("drawings", [])),
            "pine_path": str(GENERATED_PATH),
            "pine_size": len(pine),
            "preview": pine,
        }

    # Defer the import — keeps the dry-run path independent of
    # the playwright/preflight stack.
    from . import pine_editor
    result = await pine_editor.apply(
        GENERATED_PATH, name=name, check_errors=True,
    )
    result["drawing_count"] = len(spec.get("drawings", []))
    result["pine_path"] = str(GENERATED_PATH)
    return result


async def clear(name: str = DEFAULT_INDICATOR_NAME) -> dict:
    """Remove a drawings indicator from the chart by name.

    Delegates to `indicators.remove_indicator`, which targets the
    indicator legend's per-row delete button. If you applied a sketch
    with a custom `name`, pass that same name here."""
    from . import indicators
    return await indicators.remove_indicator(name)


def example_spec() -> dict:
    """A demo sketch covering all five drawing types. Useful for first-
    time users — `tv drawings example | tv drawings sketch --stdin`."""
    return {
        "name": "TV Automation Drawings (example)",
        "drawings": [
            {
                "type": "horizontal",
                "price": 27000,
                "color": "blue",
                "style": "dashed",
                "width": 1,
                "label": "Example resistance",
            },
            {
                "type": "trend_line",
                "p1": ["2026-04-15T09:30", 26800.0],
                "p2": ["2026-04-17T15:00", 27200.0],
                "color": "orange",
                "width": 2,
                "extend": "right",
            },
            {
                "type": "box",
                "p1": ["2026-04-16T09:30", 26900.0],
                "p2": ["2026-04-17T15:00", 27100.0],
                "border_color": "green",
                "bg_color": "green",
                "bg_alpha": 90,
            },
            {
                "type": "label",
                "at": ["2026-04-17T12:00", 27050.0],
                "text": "Recent high",
                "color": "blue",
                "size": "normal",
            },
            {
                "type": "vertical",
                "time": "2026-04-17T15:00",
                "color": "purple",
                "label": "Pivot",
            },
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_spec(path_or_stdin: str | None, use_stdin: bool) -> dict:
    if use_stdin:
        return json.loads(sys.stdin.read())
    if not path_or_stdin:
        raise ValueError("provide a path or --stdin")
    return json.loads(Path(path_or_stdin).read_text())


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.drawings")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sketch", help="Apply a JSON sketch to the chart")
    s.add_argument("path", nargs="?", help="Path to a sketch JSON file (or use --stdin)")
    s.add_argument("--stdin", action="store_true", help="Read JSON from stdin")
    s.add_argument("--dry-run", action="store_true",
                   help="Emit Pine to /tmp without applying — preview only")

    cl = sub.add_parser("clear", help="Remove a drawings indicator from the chart")
    cl.add_argument("--name", default=DEFAULT_INDICATOR_NAME,
                    help="Indicator name to remove (default: %(default)r)")
    sub.add_parser("example", help="Print an example sketch JSON to stdout")

    args = p.parse_args()
    if args.cmd == "sketch":
        spec = _load_spec(args.path, args.stdin)
        run(lambda: sketch(spec, dry_run=args.dry_run))
    elif args.cmd == "clear":
        run(lambda: clear(args.name))
    elif args.cmd == "example":
        print(json.dumps(example_spec(), indent=2))


if __name__ == "__main__":
    _main()
