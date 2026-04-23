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


# ---------------------------------------------------------------------------
# Per-pattern calibration — accuracy by prediction_tag value
# ---------------------------------------------------------------------------
# Walks all reconciliations + their paired pre_session forecasts; for each
# (field, value) tag the model predicted, counts how often it landed in
# `tags_correct` vs `tags_wrong` in the grade. Surfaces which prediction
# patterns are worth trusting.

_KNOWN_TAG_FIELDS = (
    "direction", "structure", "open_type",
    "lunch_behavior", "afternoon_drive",
    "goat_direction", "close_near_extreme",
    # Pivot-forecast dimensions — sourced from `invalidation_HHMM.json`
    # stages, not the pre_session.
    "pivot_classification",
)


@dataclass
class PatternStat:
    field: str           # e.g. "open_type"
    value: str           # e.g. "open_dip_then_reclaim"
    correct: int = 0
    wrong: int = 0
    sources: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.correct + self.wrong

    @property
    def pct_correct(self) -> float:
        return (self.correct / self.total) if self.total else 0.0


def collect_calibration(
    forecasts_root: Path | None = None,
    *, min_occurrences: int = 1,
) -> list[PatternStat]:
    """Aggregate prediction-tag accuracy across all reconciliations.

    For each reconciliation, look up the paired pre_session forecast's
    prediction_tags. For each (field, value), check whether the value
    appears in the reconciliation's grades.*.tags_correct / tags_wrong.
    A predicted tag that doesn't appear in either list is skipped — the
    reconciler simply didn't grade it.

    Returns sorted by total occurrences desc, then pct_correct desc.
    """
    root = forecasts_root or _FORECASTS_ROOT
    if not root.exists():
        return []

    by_key: dict[tuple[str, str], PatternStat] = {}

    for rf in sorted(root.glob("*_reconciliation.json")):
        try:
            recon = json.loads(rf.read_text())
        except Exception:
            continue
        date_str = recon.get("date")
        symbol = recon.get("symbol", "MNQ1")
        if not date_str:
            continue

        # Pair with the pre_session forecast — that's where prediction_tags lives.
        pre_path = root / f"{symbol}_{date_str}_pre_session.json"
        if not pre_path.exists():
            # Fallback: in-session forecasts may carry their own prediction_tags
            # in the future, but today only pre_session does.
            continue
        try:
            pre = json.loads(pre_path.read_text())
        except Exception:
            continue

        tags = dict(pre.get("prediction_tags") or {})
        # Also harvest pivot_classification from any pivot stages fired
        # that day. A day can have multiple pivots — we record each as
        # its own aggregation row (classification is the whole "tag").
        pivot_tags: list[dict] = []
        for pf in sorted(root.glob(f"{symbol}_{date_str}_invalidation_*.json")):
            try:
                piv = json.loads(pf.read_text())
                pc = piv.get("pivot_classification")
                if isinstance(pc, str) and pc.strip():
                    pivot_tags.append({"pivot_classification": pc.strip()})
            except Exception:
                continue

        # Aggregate tags_correct / tags_wrong across ALL stages of this recon —
        # any stage that flagged the tag correct/wrong contributes.
        all_correct: set[str] = set()
        all_wrong: set[str] = set()
        for grade in (recon.get("grades") or {}).values():
            if not isinstance(grade, dict):
                continue
            for v in (grade.get("tags_correct") or []):
                if isinstance(v, str):
                    all_correct.add(v.strip())
            for v in (grade.get("tags_wrong") or []):
                if isinstance(v, str):
                    all_wrong.add(v.strip())

        # Walk both pre-session prediction tags AND any pivot-classification
        # tags from that day's pivot stages through the same grading
        # pipeline. Promote each tag to a row in `by_key` when either
        # form appears in the graded tags_correct / tags_wrong sets.
        def _ingest(fld: str, val: str) -> None:
            if fld not in _KNOWN_TAG_FIELDS or not isinstance(val, str):
                return
            val = val.strip()
            if not val:
                return
            # The reconciler is inconsistent — different days emit grades in
            # different shapes. We accept any of:
            #   - field name alone        ("direction", "open_type")
            #   - value alone             ("up", "open_dip_then_reclaim")
            #   - field_value compound    ("direction_up")
            # If any form matches in tags_correct/wrong, the tag is graded.
            candidates = {fld, val, f"{fld}_{val}"}
            in_correct = bool(candidates & all_correct)
            in_wrong = bool(candidates & all_wrong)
            if not (in_correct or in_wrong):
                return  # ungraded, skip
            key = (fld, val)
            stat = by_key.get(key) or PatternStat(field=fld, value=val)
            if in_correct and not in_wrong:
                stat.correct += 1
            elif in_wrong and not in_correct:
                stat.wrong += 1
            else:
                # Conflicting grade across stages — bias generous (was right
                # at least once); these cases are rare and noisy.
                stat.correct += 1
            if date_str not in stat.sources:
                stat.sources.append(date_str)
            by_key[key] = stat

        for fld, val in tags.items():
            _ingest(fld, val)
        for pivot_set in pivot_tags:
            for fld, val in pivot_set.items():
                _ingest(fld, val)

    stats = [s for s in by_key.values() if s.total >= min_occurrences]
    stats.sort(key=lambda s: (s.total, s.pct_correct), reverse=True)
    return stats


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
