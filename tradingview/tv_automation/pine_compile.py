"""Read Pine Editor compile errors via the Monaco editor's marker API.

Closes a long-standing blind spot: `apply_pine.py` clicks Save+Add and
trusts the subprocess exit code, but TradingView accepts a save with
syntax errors silently — the Pine Editor shows red squiggles, the
console logs `error 1/0:` lines, and the user only finds out hours
later when the indicator never rendered.

Monaco itself exposes every diagnostic via `editor.getModelMarkers()`,
which returns the same severity/line/column/message data the editor's
underline UI is rendered from. The catch: Monaco's outer instance is
behind React fiber on the `.pine-editor-monaco` container — there's no
window-global to grab. The fiber walk below mirrors how
tradesdontlie/tradingview-mcp finds it: starting from the container DOM
node, climb up to the first parent carrying a React fiber key, then
walk fiber `.return` chain until a node's `memoizedProps.value.monacoEnv`
exposes `editor.getEditors()`. That's the same surface the editor's
own toolbar uses, so it stays consistent across recent TV builds.

Markers come back with Monaco's severity codes: 1=Hint, 2=Info,
4=Warning, 8=Error. We filter to severity >= 4 so info-level lints
don't trigger the parse-failure path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .lib import audit


_MONACO_FIBER_WALK = r"""
(function findMonacoEditor() {
  var container = document.querySelector('.monaco-editor.pine-editor-monaco')
                || document.querySelector('.pine-editor-monaco');
  if (!container) return null;
  var el = container;
  var fiberKey;
  for (var i = 0; i < 20; i++) {
    if (!el) break;
    fiberKey = Object.keys(el).find(function(k) {
      return k.startsWith('__reactFiber$');
    });
    if (fiberKey) break;
    el = el.parentElement;
  }
  if (!fiberKey) return null;
  var current = el[fiberKey];
  for (var d = 0; d < 15; d++) {
    if (!current) break;
    if (current.memoizedProps && current.memoizedProps.value
        && current.memoizedProps.value.monacoEnv) {
      var env = current.memoizedProps.value.monacoEnv;
      if (env.editor && typeof env.editor.getEditors === 'function') {
        var editors = env.editor.getEditors();
        if (editors.length > 0) return { editor: editors[0], env: env };
      }
    }
    current = current.return;
  }
  return null;
})()
"""


_SEVERITY_LABEL = {1: "hint", 2: "info", 4: "warning", 8: "error"}


async def read_compile_errors(page: Page) -> list[dict[str, Any]] | None:
    """Return Monaco diagnostics for the open Pine script, or None if
    the editor isn't reachable. Each entry: `{severity, severity_label,
    line, column, message}`. Only severity >= 4 (warning/error) is
    returned; hints/info would otherwise spam the parse-failure path."""
    raw = await page.evaluate(f"""() => {{
        var m = {_MONACO_FIBER_WALK};
        if (!m) return null;
        try {{
            var model = m.editor.getModel();
            if (!model) return [];
            var markers = m.env.editor.getModelMarkers({{ resource: model.uri }});
            return markers.map(function(mk) {{
                return {{
                    severity: mk.severity,
                    line: mk.startLineNumber,
                    column: mk.startColumn,
                    message: mk.message,
                    source: mk.source || null,
                }};
            }});
        }} catch (e) {{
            return {{ error: e.message || String(e) }};
        }}
    }}""")
    if raw is None:
        return None
    if isinstance(raw, dict) and "error" in raw:
        audit.log("pine_compile.read_fail", err=raw["error"])
        return None
    return [
        {**m, "severity_label": _SEVERITY_LABEL.get(m["severity"], "unknown")}
        for m in raw
        if m.get("severity", 0) >= 4
    ]


async def read_compile_summary(page: Page) -> dict[str, Any]:
    """Convenience wrapper: returns `{available, errors, warnings, items}`.
    `available=False` means the Monaco fiber wasn't found — caller
    should treat as 'unknown', not 'clean'."""
    items = await read_compile_errors(page)
    if items is None:
        return {"available": False, "errors": 0, "warnings": 0, "items": []}
    errors = sum(1 for m in items if m["severity"] == 8)
    warnings = sum(1 for m in items if m["severity"] == 4)
    return {"available": True, "errors": errors,
            "warnings": warnings, "items": items}


def write_failure_dump(
    pine_source: str, summary: dict[str, Any], dump_dir: Path,
    *, stem: str,
) -> Path:
    """Persist a compile failure for later inspection. Writes a single
    text file with the diagnostics header followed by the full source
    so the operator can re-run the LLM offline against the same input."""
    dump_dir.mkdir(parents=True, exist_ok=True)
    path = dump_dir / f"compile_fail_{stem}.txt"
    lines = [
        f"errors={summary['errors']} warnings={summary['warnings']}",
        "",
    ]
    for m in summary["items"]:
        lines.append(
            f"  [{m['severity_label']}] line {m['line']}:{m['column']} — "
            f"{m['message']}"
        )
    lines.append("")
    lines.append("--- SOURCE ---")
    lines.append(pine_source)
    path.write_text("\n".join(lines))
    return path
