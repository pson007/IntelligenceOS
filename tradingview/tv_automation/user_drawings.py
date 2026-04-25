"""Read user-drawn annotations (trend lines, horizontal levels,
rectangles, text labels) from the live chart and surface them as
explicit context for vision-LLM analysis.

The analyze pipeline currently sees the chart only through the
screenshot — every manually-drawn level the trader cares about is
just a few pixels in the PNG. The LLM occasionally misreads them or
ignores them. This module pulls them as structured data via TV's
`chart.getAllShapes()` API, formats them as a markdown block, and
lets the analyze prompts include "User-curated levels" as a first-
class signal.

Pattern lifted from tradesdontlie/tradingview-mcp's `drawing.js`:
- `chart.getAllShapes()` → list of `{id, name}`
- `chart.getShapeById(id).getPoints()` → list of `{time, price}`
- `chart.getShapeById(id).getProperties()` → tool-specific metadata

We classify shapes by name into three buckets:
  - HORIZONTAL — `Horizontal Line`, `Horizontal Ray` (single-price levels)
  - SLOPED — `Trend Line`, `Trend Angle` (two-point lines, often diagonal
    support/resistance)
  - RECT — `Rectangle`, `Long Position`, `Short Position` (price zones)
  - LABEL — `Text`, `Note`, `Anchored Note` (annotations with text content)

Other shape types are returned in `other` for completeness but not
formatted into the prompt block — the four buckets above cover ~95%
of what traders actually use as levels.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Page

from .lib import audit


_SHAPES_PATH = "window.TradingViewApi._activeChartWidgetWV.value()"


_HORIZONTAL_NAMES = {
    "Horizontal Line", "Horizontal Ray", "horizontal_line",
    "horizontal_ray", "LineToolHorzLine", "LineToolHorzRay",
}
_SLOPED_NAMES = {
    "Trend Line", "Trend Angle", "trend_line", "LineToolTrendLine",
    "LineToolTrendAngle", "Ray", "Extended Line",
}
_RECT_NAMES = {
    "Rectangle", "rectangle", "LineToolRectangle", "Long Position",
    "Short Position", "LineToolRiskRewardLong", "LineToolRiskRewardShort",
}
_LABEL_NAMES = {
    "Text", "Note", "Anchored Note", "Callout", "LineToolText",
    "LineToolNote", "LineToolAnchoredNote", "LineToolCallout", "Price Label",
}


_READ_SHAPES_JS = r"""
() => {
    const out = {available: false, shapes: [], err: null};
    try {
        const c = window.TradingViewApi._activeChartWidgetWV.value();
        if (!c || typeof c.getAllShapes !== 'function') {
            out.err = 'getAllShapes_unavailable';
            return out;
        }
        out.available = true;
        const shapes = c.getAllShapes();
        if (!Array.isArray(shapes)) {
            out.err = 'getAllShapes_returned_non_array';
            return out;
        }
        for (const s of shapes) {
            const id = s.id || s.entity_id || null;
            const name = s.name || s.shape || s.tool || null;
            if (!id) continue;
            let points = null, props = null, text = null, lock = null;
            try {
                const obj = (typeof c.getShapeById === 'function')
                    ? c.getShapeById(id) : null;
                if (obj) {
                    if (typeof obj.getPoints === 'function') {
                        points = obj.getPoints();
                    }
                    if (typeof obj.getProperties === 'function') {
                        const p = obj.getProperties();
                        // Properties objects can be huge; just keep the
                        // small metadata fields useful for context.
                        if (p) {
                            props = {
                                color: p.color || p.linecolor || null,
                                style: p.style || p.linestyle || null,
                                width: p.width || p.linewidth || null,
                                visible: p.visible !== undefined ? p.visible : null,
                                locked: p.locked || null,
                                frozen: p.frozen || null,
                            };
                            text = p.text || null;
                        }
                    }
                    if (typeof obj.isLocked === 'function') {
                        lock = obj.isLocked();
                    }
                }
            } catch (e) {}
            out.shapes.push({
                id: String(id), name: name,
                points: (points || []).map(pt => ({
                    time: pt.time || null,
                    price: typeof pt.price === 'number'
                        ? Number(pt.price.toFixed(2)) : pt.price,
                })),
                text: text, properties: props, locked: lock,
            });
        }
    } catch (e) { out.err = (e && e.message) || String(e); }
    return out;
};
"""


def _classify(name: str | None) -> str:
    if not name:
        return "other"
    if name in _HORIZONTAL_NAMES:
        return "horizontal"
    if name in _SLOPED_NAMES:
        return "sloped"
    if name in _RECT_NAMES:
        return "rect"
    if name in _LABEL_NAMES:
        return "label"
    return "other"


async def read_user_drawings(page: Page) -> dict[str, Any]:
    """Return `{available, shapes, by_kind, err}` snapshot of all
    user-drawn shapes on the chart. `by_kind` buckets shapes into
    horizontal/sloped/rect/label/other for fast prompt construction."""
    try:
        raw = await page.evaluate(_READ_SHAPES_JS)
    except Exception as e:
        audit.log("user_drawings.read.fail", err=str(e))
        return {"available": False, "shapes": [], "by_kind": {}, "err": str(e)}

    shapes = raw.get("shapes") or []
    by_kind: dict[str, list] = {
        "horizontal": [], "sloped": [], "rect": [], "label": [], "other": [],
    }
    for s in shapes:
        s["kind"] = _classify(s.get("name"))
        by_kind[s["kind"]].append(s)

    summary = {
        "available": raw.get("available", False),
        "err": raw.get("err"),
        "total": len(shapes),
        "by_kind_counts": {k: len(v) for k, v in by_kind.items()},
    }
    audit.log("user_drawings.read", **summary)

    return {**summary, "shapes": shapes, "by_kind": by_kind}


def _fmt_time(epoch_s: Any) -> str:
    if not isinstance(epoch_s, (int, float)):
        return "?"
    try:
        dt = datetime.fromtimestamp(epoch_s, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "?"


def format_for_prompt(
    drawings: dict[str, Any], *, max_per_kind: int = 8,
) -> str | None:
    """Render the drawings dict as a markdown block ready to inject
    into a vision-LLM prompt. Returns None when nothing's drawn so the
    prompt stays unchanged.

    Compact by design — only the price levels (and timestamps for
    sloped lines) so the LLM can correlate to the screenshot. Skips
    `other` bucket entirely; if it matters, the user named it
    something the classifier didn't recognize and we don't want to
    pollute the prompt with noise."""
    by_kind = drawings.get("by_kind") or {}
    if drawings.get("total", 0) == 0:
        return None

    lines: list[str] = ["## USER-DRAWN LEVELS (pulled from chart, exact prices)"]
    any_content = False

    horiz = by_kind.get("horizontal") or []
    if horiz:
        any_content = True
        prices = sorted({
            pt["price"] for s in horiz for pt in (s.get("points") or [])
            if isinstance(pt.get("price"), (int, float))
        }, reverse=True)
        if prices:
            shown = prices[:max_per_kind]
            lines.append("- **Horizontal levels** (key support/resistance "
                         "the user has marked): "
                         + ", ".join(f"{p:g}" for p in shown))

    sloped = by_kind.get("sloped") or []
    if sloped:
        any_content = True
        lines.append("- **Trend lines / rays** (sloped — direction matters):")
        for s in sloped[:max_per_kind]:
            pts = s.get("points") or []
            if len(pts) >= 2:
                p1, p2 = pts[0], pts[1]
                lines.append(
                    f"  - {p1.get('price', '?'):g} @ {_fmt_time(p1.get('time'))} → "
                    f"{p2.get('price', '?'):g} @ {_fmt_time(p2.get('time'))}"
                )

    rects = by_kind.get("rect") or []
    if rects:
        any_content = True
        lines.append("- **Boxes / risk-reward zones**:")
        for r in rects[:max_per_kind]:
            pts = r.get("points") or []
            ys = [p.get("price") for p in pts
                  if isinstance(p.get("price"), (int, float))]
            if len(ys) >= 2:
                hi, lo = max(ys), min(ys)
                lines.append(
                    f"  - {r.get('name', 'Rect')}: {lo:g} → {hi:g} "
                    f"(range {hi - lo:g}pts)"
                )

    labels = by_kind.get("label") or []
    if labels:
        any_content = True
        lines.append("- **Text annotations** (the user's notes on the chart):")
        for lab in labels[:max_per_kind]:
            txt = (lab.get("text") or "").strip().replace("\n", " ")[:120]
            pts = lab.get("points") or []
            price = pts[0].get("price") if pts else None
            if txt or price is not None:
                price_str = f"@ {price:g}" if isinstance(price, (int, float)) else ""
                lines.append(f"  - {price_str} {txt!r}".strip())

    return "\n".join(lines) if any_content else None


async def _cli_main() -> None:
    from .lib.context import chart_session
    p = argparse.ArgumentParser(prog="tv_automation.user_drawings")
    p.add_argument("--prompt", action="store_true",
                   help="Print the formatted prompt block instead of JSON")
    args = p.parse_args()

    async with chart_session() as (_ctx, page):
        drawings = await read_user_drawings(page)
        if args.prompt:
            block = format_for_prompt(drawings)
            print(block or "(no user drawings on chart)")
        else:
            # Trim shapes detail to keep CLI output readable.
            print(json.dumps({
                "available": drawings["available"],
                "total": drawings["total"],
                "by_kind_counts": drawings["by_kind_counts"],
                "err": drawings.get("err"),
                "sample": drawings["shapes"][:5],
            }, indent=2))


if __name__ == "__main__":
    asyncio.run(_cli_main())
