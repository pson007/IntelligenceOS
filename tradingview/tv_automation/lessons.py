"""Reconciliation Lessons aggregator.

Each reconciliation JSON file produces a `lessons` array of 3-5 actionable
bullet sentences. Over time those accumulate. This module reads them all,
dedupes near-identical phrasings, ranks by occurrence frequency, and
returns a flat list — used by:

  * `daily_forecast.py` to auto-inject the top-N lessons into forecast and
    reconcile prompts at runtime (closing the feedback loop).
  * `ui_server.py` `/api/forecasts/lessons` to render a Lessons card in
    the Forecasts tab UI.

Dedup is deliberately simple: lowercase + strip leading ordinal/punctuation
+ collapse whitespace. Catches reorderings of the same lesson without
needing embeddings. With a richer corpus we could upgrade to embedding-
based clustering, but at <100 reconciliations the simple normalization
covers the realistic duplication patterns.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path


_FORECASTS_ROOT = (Path(__file__).parent.parent / "forecasts").resolve()


@dataclass
class Lesson:
    """A deduped lesson aggregated from one or more reconciliations."""
    text: str  # canonical (first-seen) phrasing
    count: int = 1
    sources: list[str] = field(default_factory=list)  # date strings


_NORMALIZE_RX = re.compile(r"[^\w\s]")
_LEAD_NUMBER_RX = re.compile(r"^\s*\d+[.):]\s*")


def _normalize(text: str) -> str:
    """Cheap canonicalization for dedup comparison."""
    s = text.strip()
    s = _LEAD_NUMBER_RX.sub("", s)  # strip "1.", "2)", etc.
    s = s.lower()
    s = _NORMALIZE_RX.sub(" ", s)   # punctuation → space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def collect_lessons(forecasts_root: Path | None = None) -> list[Lesson]:
    """Walk all `*_reconciliation.json` files and aggregate their `lessons` arrays.

    Returns lessons sorted by:
      1. Occurrence count (desc) — repeated lessons rank higher
      2. Most-recent source date (desc) — recent reinforcement wins ties

    Each lesson keeps its first-seen canonical phrasing for display.
    """
    root = forecasts_root or _FORECASTS_ROOT
    if not root.exists():
        return []

    by_norm: OrderedDict[str, Lesson] = OrderedDict()
    for jf in sorted(root.glob("*_reconciliation.json")):
        try:
            data = json.loads(jf.read_text())
        except Exception:
            continue
        date = data.get("date") or jf.stem
        for raw in (data.get("lessons") or []):
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = _normalize(raw)
            if not key:
                continue
            if key in by_norm:
                lesson = by_norm[key]
                lesson.count += 1
                if date not in lesson.sources:
                    lesson.sources.append(date)
            else:
                by_norm[key] = Lesson(text=raw.strip(), count=1, sources=[date])

    lessons = list(by_norm.values())
    # Stable two-pass sort: secondary key first (most-recent-source desc),
    # then primary (occurrence count desc) — Python's sort preserves order
    # of equal primary keys so the secondary ordering survives.
    lessons.sort(key=lambda l: max(l.sources) if l.sources else "", reverse=True)
    lessons.sort(key=lambda l: l.count, reverse=True)
    return lessons


def top_lessons(n: int = 8, forecasts_root: Path | None = None) -> list[Lesson]:
    """Convenience: top-N lessons (ranked per `collect_lessons`)."""
    return collect_lessons(forecasts_root)[:n]


def format_for_prompt(n: int = 8, forecasts_root: Path | None = None) -> str:
    """Render top lessons as a markdown bullet list for prompt injection.

    Returns empty string when no lessons exist yet — caller should
    omit the section header rather than render an empty list.
    """
    lessons = top_lessons(n, forecasts_root)
    if not lessons:
        return ""
    lines = []
    for l in lessons:
        suffix = f"  *(seen {l.count}× across {len(l.sources)} day{'s' if len(l.sources) != 1 else ''})*" if l.count > 1 else ""
        lines.append(f"- {l.text}{suffix}")
    return "\n".join(lines)


def to_dicts(lessons: list[Lesson]) -> list[dict]:
    """Plain-dict serialization for JSON endpoints."""
    return [
        {"text": l.text, "count": l.count, "sources": l.sources}
        for l in lessons
    ]
