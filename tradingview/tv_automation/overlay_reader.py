"""Read back drawings rendered by Pine indicators on the chart.

Closes the loop between "the forecast JSON says HOD target 27200" and
"the chart shows that line at 27200". Without this, a Pine logic bug
or a stale-state bug (overlay drawn against yesterday's prices) is
only visible by eyeball — and the analyze pipeline that grades the
overlay is reading a SCREENSHOT of it, so it can't disagree with
itself in any useful way.

TradingView keeps Pine's `line`/`label`/`box` primitives in
graphics collections under each study's `_graphics._primitivesCollection`.
The MCP's data.js walks the same path; we mirror it here, scoped to a
single study at a time so we can ask "what did the Forecast Overlay
study draw?" rather than getting every drawing on the chart.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from .lib import audit


_OVERLAY_READER_JS = r"""
(filter) => {
  try {
    const widget = window.TradingViewApi._activeChartWidgetWV.value();
    if (!widget) return {available: false, reason: 'no_widget'};
    const chart = widget._chartWidget;
    if (!chart || !chart.model) return {available: false, reason: 'no_chart_widget'};
    const sources = chart.model().model().dataSources();
    if (!sources) return {available: false, reason: 'no_data_sources'};

    const fl = (filter || '').toLowerCase();
    const matched = [];
    for (let i = 0; i < sources.length; i++) {
      const s = sources[i];
      if (!s.metaInfo) continue;
      let info;
      try { info = s.metaInfo(); } catch (e) { continue; }
      const name = (info.description || info.shortDescription
                    || info.id || '').toString();
      if (fl && name.toLowerCase().indexOf(fl) === -1) continue;

      const lines = [], labels = [], boxes = [];
      const g = s._graphics;
      const pc = g && g._primitivesCollection;
      if (pc) {
        // dwglines
        try {
          const outer = pc.dwglines;
          const inner = outer && outer.get && outer.get('lines');
          const coll = inner && inner.get && inner.get(false);
          if (coll && coll._primitivesDataById) {
            coll._primitivesDataById.forEach((v, id) => {
              lines.push({
                id: id,
                y1: typeof v.y1 === 'number' ? Number(v.y1.toFixed(2)) : v.y1,
                y2: typeof v.y2 === 'number' ? Number(v.y2.toFixed(2)) : v.y2,
                x1: v.x1, x2: v.x2,
              });
            });
          }
        } catch (e) {}
        // dwglabels
        try {
          const outer = pc.dwglabels;
          const inner = outer && outer.get && outer.get('labels');
          const coll = inner && inner.get && inner.get(false);
          if (coll && coll._primitivesDataById) {
            coll._primitivesDataById.forEach((v, id) => {
              labels.push({
                id: id,
                text: v.t || v.text || null,
                y: typeof v.y === 'number' ? Number(v.y.toFixed(2)) : v.y,
                x: v.x,
              });
            });
          }
        } catch (e) {}
        // dwgboxes
        try {
          const outer = pc.dwgboxes;
          const inner = outer && outer.get && outer.get('boxes');
          const coll = inner && inner.get && inner.get(false);
          if (coll && coll._primitivesDataById) {
            coll._primitivesDataById.forEach((v, id) => {
              const high = (typeof v.y1 === 'number' && typeof v.y2 === 'number')
                ? Number(Math.max(v.y1, v.y2).toFixed(2)) : null;
              const low = (typeof v.y1 === 'number' && typeof v.y2 === 'number')
                ? Number(Math.min(v.y1, v.y2).toFixed(2)) : null;
              boxes.push({id: id, high: high, low: low,
                          x1: v.x1, x2: v.x2});
            });
          }
        } catch (e) {}
      }

      matched.push({
        study_id: s.id ? s.id() : null,
        name: name,
        lines: lines, labels: labels, boxes: boxes,
        counts: {lines: lines.length, labels: labels.length,
                 boxes: boxes.length},
      });
    }
    return {available: true, matched_count: matched.length, studies: matched};
  } catch (e) {
    return {available: false, reason: 'exception', error: String(e)};
  }
}
"""


async def read_study_drawings(
    page: Page, name_filter: str = "",
) -> dict[str, Any] | None:
    """Walk every loaded data source and collect Pine line/label/box
    primitives. `name_filter` matches against the study's metaInfo
    description (case-insensitive substring); pass `""` for all studies.

    Returns `{available, matched_count, studies: [{study_id, name,
    lines, labels, boxes, counts}]}` or `None` on hard error.

    `name_filter` is passed via Playwright's `evaluate` arg parameter,
    so it's serialized as JSON — caller-supplied strings can't inject
    JS even if they ever flow from less-trusted sources."""
    try:
        result = await page.evaluate(_OVERLAY_READER_JS, name_filter)
    except Exception as e:
        audit.log("overlay_reader.fail", err=str(e))
        return None
    if not result.get("available"):
        audit.log("overlay_reader.unavailable",
                  reason=result.get("reason"), filter=name_filter)
    return result


async def verify_overlay_lines(
    page: Page, name_filter: str, expected: dict[str, float],
    *, tolerance_pts: float = 1.0,
) -> dict[str, Any]:
    """Compare drawn line prices against `expected` (label → price).
    Returns `{matched_studies, drift: [{label, expected, found,
    delta_pts}], ok}`. `ok=True` when every expected label found a
    drawn line within `tolerance_pts`.

    Match strategy: find the drawn line whose y1 is closest to the
    expected price. If `delta > tolerance_pts`, it's drift. If no
    line is within `tolerance_pts * 50` of any expected price, mark
    `found=None` (label likely wasn't drawn at all)."""
    drawings = await read_study_drawings(page, name_filter)
    if not drawings or not drawings.get("studies"):
        return {"matched_studies": 0, "drift": [], "ok": False,
                "reason": "no_studies_matched"}

    all_lines: list[dict[str, Any]] = []
    for s in drawings["studies"]:
        all_lines.extend(s.get("lines") or [])

    drift: list[dict[str, Any]] = []
    for label, expected_px in expected.items():
        if not all_lines:
            drift.append({"label": label, "expected": expected_px,
                          "found": None, "delta_pts": None})
            continue
        nearest = min(
            (ln for ln in all_lines if isinstance(ln.get("y1"), (int, float))),
            key=lambda ln: abs(ln["y1"] - expected_px),
            default=None,
        )
        if nearest is None:
            drift.append({"label": label, "expected": expected_px,
                          "found": None, "delta_pts": None})
            continue
        delta = round(abs(nearest["y1"] - expected_px), 2)
        drift.append({
            "label": label,
            "expected": expected_px,
            "found": nearest["y1"],
            "delta_pts": delta,
            "within_tol": delta <= tolerance_pts,
        })

    ok = all(d.get("within_tol") for d in drift) if drift else True
    audit.log("overlay_reader.verify",
              filter=name_filter, ok=ok, count=len(drift),
              max_drift=max((d.get("delta_pts") or 0) for d in drift)
                        if drift else 0)
    return {"matched_studies": drawings["matched_count"],
            "drift": drift, "ok": ok}
