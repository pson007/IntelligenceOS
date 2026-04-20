"""Export an analyze result to JSON / Markdown / PNG / PDF.

Powers `/api/analyze/export/{task_id}` in ui_server.py. Takes the full
result dict from `_analyze_tasks[task_id]["result"]` (so screenshot
paths, per-TF breakdowns, pine code, calibration — every field present
at analyze-time — survive into the export) plus the format and returns
(bytes, media_type, filename).

Why the source is the live task dict and not `decisions.db`:
  * `decisions.db` doesn't store the screenshot path or per-TF data
  * the just-finished result is already in memory
  * historical re-exports (from Journal) can fall back to the DB later
"""

from __future__ import annotations

import base64
import html
import json
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Filename
# ---------------------------------------------------------------------------


def filename_base(result: dict) -> str:
    """e.g. `analysis-MNQ1-5m-20260420T101234`. Safe for all filesystems;
    easy to sort by timestamp when you accumulate many exports."""
    symbol = str(result.get("symbol") or "unknown")
    tf = str(result.get("timeframe") or result.get("mode") or "")
    ts = result.get("iso_ts") or time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                               time.localtime())
    # Compact and strip separators that confuse OSes.
    safe_sym = symbol.replace("/", "_").replace("!", "").replace(":", "_")
    safe_tf = tf.replace("/", "_").replace(" ", "")
    # Take 2026-04-20T10:12:34-0400 → 20260420T101234
    safe_ts = ts.replace("-", "").replace(":", "")[:15]
    parts = [p for p in ("analysis", safe_sym, safe_tf, safe_ts) if p]
    return "-".join(parts)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(result: dict) -> bytes:
    """Pretty-printed JSON of the full result dict. Round-trippable as
    an archival format: everything the UI saw, preserved verbatim."""
    return json.dumps(result, indent=2, default=str).encode("utf-8")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def to_markdown(result: dict) -> bytes:
    """Human-readable report for notes/wikis. Structured for scanning
    top-to-bottom: metadata → verdict → rationale → details."""
    lines: list[str] = []
    mode = result.get("mode") or "single"
    symbol = result.get("symbol") or "?"
    tf = result.get("timeframe") or result.get("optimal_tf") or ""
    title_tf = f" · {tf}" if tf else ""
    lines.append(f"# Analysis — {symbol}{title_tf}"
                 f"{' · deep' if mode == 'deep' else ''}")
    lines.append("")

    # Metadata block
    lines.append("## Metadata")
    lines.append(_md_kv("Timestamp", result.get("iso_ts")))
    lines.append(_md_kv("Symbol", symbol))
    if mode == "deep":
        tfs = result.get("timeframes")
        lines.append(_md_kv("Timeframes", ", ".join(tfs) if tfs else None))
        lines.append(_md_kv("Optimal TF", result.get("optimal_tf")))
    else:
        lines.append(_md_kv("Timeframe", result.get("timeframe")))
    lines.append(_md_kv("Provider", result.get("provider")))
    lines.append(_md_kv("Model", result.get("model")))
    cost = result.get("cost_usd")
    if cost is not None:
        lines.append(_md_kv("Cost (USD)", f"${cost:.4f}"))
    elapsed = result.get("elapsed_s")
    if elapsed is not None:
        lines.append(_md_kv("Elapsed", f"{elapsed}s"))
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append(_md_kv("Signal", result.get("signal")))
    conf = result.get("confidence")
    lines.append(_md_kv("Confidence", f"{conf}%" if conf is not None else None))
    lines.append(_md_kv("Entry", result.get("entry")))
    lines.append(_md_kv("Stop", result.get("stop")))
    lines.append(_md_kv("Take Profit", result.get("tp")))
    rr = _compute_rr(result)
    if rr is not None:
        lines.append(_md_kv("R:R", f"{rr:.2f}"))
    lines.append("")

    # Rationale
    rationale = result.get("rationale")
    if rationale:
        lines.append("## Rationale")
        lines.append(str(rationale).strip())
        lines.append("")

    # Unknowns
    unknowns = result.get("unknowns") or []
    if unknowns:
        lines.append("## What could change the call")
        for u in unknowns:
            if isinstance(u, dict):
                what = u.get("what", "")
                how = u.get("resolves_how", "")
                line = f"- **{what}**"
                if how:
                    line += f" — {how}"
                lines.append(line)
            else:
                lines.append(f"- {u}")
        lines.append("")

    # Per-TF table (deep only)
    per_tf = result.get("per_tf") or []
    if mode == "deep" and per_tf:
        lines.append("## Per-timeframe breakdown")
        lines.append("| TF | Signal | Confidence | Entry | Stop | TP | Notes |")
        lines.append("|---|---|---|---|---|---|---|")
        optimal = result.get("optimal_tf")
        for row in per_tf:
            is_opt = "⭐ " if row.get("tf") == optimal else ""
            lines.append(
                f"| {is_opt}{row.get('tf', '—')}"
                f" | {row.get('signal', '—')}"
                f" | {row.get('confidence', '—')}"
                f" | {row.get('entry', '—')}"
                f" | {row.get('stop', '—')}"
                f" | {row.get('tp', '—')}"
                f" | {(row.get('notes') or '').replace('|', '\\|')[:80]} |"
            )
        lines.append("")

    # Chart screenshot reference
    cap_path = _capture_path(result)
    if cap_path:
        lines.append(f"## Chart")
        lines.append(f"![chart]({cap_path})")
        lines.append("")
        lines.append(f"_Screenshot saved to: `{cap_path}`_")
        lines.append("")

    # Pine script
    pine = result.get("pine_code")
    if pine:
        lines.append("## Pine Script")
        lines.append("```pinescript")
        lines.append(pine.strip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines).encode("utf-8")


def _md_kv(k: str, v: Any) -> str:
    if v is None or v == "":
        return f"- **{k}:** —"
    return f"- **{k}:** {v}"


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------


def to_png(result: dict) -> bytes | None:
    """Return the chart screenshot bytes. Deep mode: returns the optimal
    TF's screenshot if known, else the first capture.

    Returns None if no screenshot file is available — caller raises 404."""
    path = _capture_path(result)
    if not path or not Path(path).exists():
        return None
    return Path(path).read_bytes()


# ---------------------------------------------------------------------------
# PDF — via Playwright (HTML → PDF), spawning a NEW browser isolated
# from the CDP-attached session. The bundled chromium is already on
# disk from the repo's preflight, so launch is ~1s cold.
# ---------------------------------------------------------------------------


async def to_pdf(result: dict) -> bytes:
    """Render a one-page PDF report of the analysis. Self-contained —
    chart screenshot is embedded as a data URI so the PDF stands alone.

    Reuses the bundled Chromium already on disk (same binary used by
    `start_chrome_cdp.sh`) rather than downloading the separate
    "chrome-headless-shell" that recent Playwright versions default to.
    Avoids a 200MB install for a feature that doesn't need it — the
    regular Chromium renders PDFs identically."""
    html_doc = _render_html(result)
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path=_bundled_chromium_path(),
            headless=True,
        )
        try:
            page = await browser.new_page()
            await page.set_content(html_doc, wait_until="domcontentloaded")
            pdf = await page.pdf(
                format="Letter",
                print_background=True,
                margin={"top": "1.5cm", "bottom": "1.5cm",
                        "left": "1.5cm", "right": "1.5cm"},
            )
        finally:
            await browser.close()
    return pdf


def _bundled_chromium_path() -> str:
    """Resolve the newest bundled Chromium on disk. Mirrors the shell
    logic in `start_chrome_cdp.sh`."""
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    matches = sorted(
        cache.glob("chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        key=lambda p: str(p),
    )
    if not matches:
        raise RuntimeError(
            "Bundled Chromium not found under ~/Library/Caches/ms-playwright. "
            "Run `.venv/bin/playwright install chromium` to install it."
        )
    return str(matches[-1])


def _render_html(result: dict) -> str:
    """Compose the HTML used for PDF rendering. Dark theme mirrors the
    UI so exports visually match the console. Styles inlined — no
    external resources, no network during PDF rendering."""
    mode = result.get("mode") or "single"
    symbol = _h(result.get("symbol") or "?")
    tf = _h(result.get("timeframe") or result.get("optimal_tf") or "")
    ts = _h(result.get("iso_ts") or "")
    signal = result.get("signal") or "—"
    signal_color = {
        "Long":  "#3fb950",
        "Short": "#f85149",
        "Skip":  "#8b949e",
    }.get(signal, "#8b949e")
    conf = result.get("confidence")
    entry = _h(str(result.get("entry") or "—"))
    stop = _h(str(result.get("stop") or "—"))
    tp = _h(str(result.get("tp") or "—"))
    rr = _compute_rr(result)
    rr_str = f"{rr:.2f}" if rr is not None else "—"
    rationale = _h(str(result.get("rationale") or ""))
    provider = _h(result.get("provider") or "")
    model = _h(result.get("model") or "")

    # Embed chart as data URI so the PDF is self-contained.
    cap_path = _capture_path(result)
    chart_img = ""
    if cap_path and Path(cap_path).exists():
        data = base64.b64encode(Path(cap_path).read_bytes()).decode("ascii")
        chart_img = (
            f'<img class="chart" src="data:image/png;base64,{data}" '
            f'alt="chart screenshot" />'
        )

    per_tf_html = ""
    per_tf = result.get("per_tf") or []
    if mode == "deep" and per_tf:
        rows = []
        optimal = result.get("optimal_tf")
        for row in per_tf:
            star = "★ " if row.get("tf") == optimal else ""
            rows.append(
                f"<tr>"
                f"<td>{star}{_h(str(row.get('tf', '—')))}</td>"
                f"<td>{_h(str(row.get('signal', '—')))}</td>"
                f"<td>{_h(str(row.get('confidence', '—')))}</td>"
                f"<td>{_h(str(row.get('entry', '—')))}</td>"
                f"<td>{_h(str(row.get('stop', '—')))}</td>"
                f"<td>{_h(str(row.get('tp', '—')))}</td>"
                f"</tr>"
            )
        per_tf_html = (
            '<h2>Per-timeframe breakdown</h2>'
            '<table class="per-tf"><thead><tr>'
            '<th>TF</th><th>Signal</th><th>Conf</th>'
            '<th>Entry</th><th>Stop</th><th>TP</th>'
            '</tr></thead><tbody>'
            + "".join(rows) + '</tbody></table>'
        )

    unknowns = result.get("unknowns") or []
    unknowns_html = ""
    if unknowns:
        items = []
        for u in unknowns:
            if isinstance(u, dict):
                what = _h(u.get("what") or "")
                how = _h(u.get("resolves_how") or "")
                items.append(f"<li><strong>{what}</strong>"
                             + (f" — {how}" if how else "") + "</li>")
            else:
                items.append(f"<li>{_h(str(u))}</li>")
        unknowns_html = (
            '<h2>What could change the call</h2>'
            '<ul class="unknowns">' + "".join(items) + '</ul>'
        )

    deep_badge = ""
    if mode == "deep":
        deep_badge = ' <span class="badge">DEEP</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Analysis — {symbol} {tf}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   sans-serif;
      background: #0d1117;
      color: #e6edf3;
      font-size: 11pt;
      line-height: 1.45;
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
    }}
    header {{
      border-bottom: 1px solid #30363d;
      padding-bottom: 8pt;
      margin-bottom: 12pt;
    }}
    h1 {{
      margin: 0;
      font-size: 18pt;
      font-weight: 600;
    }}
    .ts {{
      color: #8b949e;
      font-size: 9pt;
      margin-top: 4pt;
    }}
    h2 {{
      font-size: 12pt;
      border-bottom: 1px solid #30363d;
      padding-bottom: 4pt;
      margin: 16pt 0 8pt;
    }}
    .verdict {{
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 4pt 16pt;
      align-items: center;
      padding: 10pt;
      background: #161b22;
      border-radius: 6pt;
      margin-bottom: 12pt;
    }}
    .signal-pill {{
      grid-row: 1 / span 4;
      align-self: center;
      padding: 8pt 14pt;
      font-size: 18pt;
      font-weight: 600;
      background: {signal_color};
      color: #0d1117;
      border-radius: 4pt;
      text-align: center;
    }}
    .kv {{
      display: contents;
    }}
    .kv .k {{ color: #8b949e; font-size: 9pt; }}
    .kv .v {{ font-weight: 500; }}
    .levels {{
      display: flex;
      gap: 20pt;
      flex-wrap: wrap;
      margin-top: 10pt;
      padding: 8pt 0;
      border-top: 1px dashed #30363d;
    }}
    .levels div {{
      display: flex;
      flex-direction: column;
    }}
    .levels .k {{ font-size: 8pt; color: #8b949e; }}
    .levels .v {{ font-size: 13pt; font-weight: 600; }}
    .rationale {{
      background: #161b22;
      padding: 10pt;
      border-radius: 4pt;
      white-space: pre-wrap;
    }}
    .chart {{
      width: 100%;
      max-width: 100%;
      border-radius: 4pt;
      border: 1px solid #30363d;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 10pt; }}
    th, td {{
      padding: 4pt 6pt;
      text-align: left;
      border-bottom: 1px solid #30363d;
    }}
    th {{ color: #8b949e; font-weight: 500; font-size: 9pt; }}
    footer {{
      margin-top: 24pt;
      padding-top: 8pt;
      border-top: 1px solid #30363d;
      color: #8b949e;
      font-size: 8pt;
    }}
    .badge {{
      display: inline-block;
      padding: 2pt 6pt;
      font-size: 8pt;
      background: #58a6ff;
      color: #0d1117;
      border-radius: 3pt;
      vertical-align: middle;
    }}
    .unknowns li {{ margin-bottom: 4pt; }}
  </style>
</head>
<body>
  <header>
    <h1>{symbol} <span class="mono">· {tf}</span>{deep_badge}</h1>
    <div class="ts">Analysis completed {ts}</div>
  </header>

  <section class="verdict">
    <div class="signal-pill">{_h(signal)}</div>
    <div class="kv"><span class="k">Confidence</span>
         <span class="v">{conf if conf is not None else "—"}%</span></div>
    <div class="kv"><span class="k">Provider</span>
         <span class="v">{provider} · {model}</span></div>
    <div style="grid-column: 2;">
      <div class="levels">
        <div><span class="k">Entry</span>
             <span class="v mono">{entry}</span></div>
        <div><span class="k">Stop</span>
             <span class="v mono">{stop}</span></div>
        <div><span class="k">Take Profit</span>
             <span class="v mono">{tp}</span></div>
        <div><span class="k">R:R</span>
             <span class="v mono">{rr_str}</span></div>
      </div>
    </div>
  </section>

  {f'<h2>Rationale</h2><div class="rationale">{rationale}</div>' if rationale else ''}

  {unknowns_html}

  {f'<h2>Chart</h2>{chart_img}' if chart_img else ''}

  {per_tf_html}

  <footer>
    IntelligenceOS · analysis exported {time.strftime("%Y-%m-%d %H:%M %Z")}
  </footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _h(s: Any) -> str:
    """HTML-escape a value for safe embedding."""
    return html.escape("" if s is None else str(s))


def _capture_path(result: dict) -> str | None:
    """Single-TF analyses have `capture.path`; deep analyses have a
    `captures[]` list. Return the most relevant screenshot — for deep,
    prefer the optimal-TF capture."""
    cap = result.get("capture")
    if isinstance(cap, dict) and cap.get("path"):
        return cap["path"]
    caps = result.get("captures") or []
    if caps:
        optimal = result.get("optimal_tf")
        for c in caps:
            if c.get("tf") == optimal and c.get("path"):
                return c["path"]
        # Fallback: first capture
        for c in caps:
            if c.get("path"):
                return c["path"]
    return None


def _compute_rr(result: dict) -> float | None:
    """Reward-to-risk from entry/stop/tp. None if any level is missing
    or stop == entry (would divide by zero)."""
    try:
        entry = float(result["entry"])
        stop = float(result["stop"])
        tp = float(result["tp"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    reward = abs(tp - entry)
    return reward / risk
