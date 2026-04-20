"""Decision log — SQLite-backed record of every Analyze / Deep run.

Phase 1 of the calibration roadmap in HumanOS Product thesis - Trading.md.
Writes one row per `analyze.done` event. Schema includes placeholder
columns for outcome reconciliation (outcome, realized_r, closed_at)
that a separate reconciler will populate later.

Design principles:
  * Non-blocking — every call is wrapped in try/except at the call
    site. A failed DB write must NEVER fail the analysis flow.
  * Append-only in spirit — we never mutate decision rows (the
    reconciler UPDATEs only the outcome.* columns, never the
    decision data itself).
  * Single file, single table. No migrations library, no ORM —
    schema evolution is a plain `ALTER TABLE` in `init_db`.
  * Same privacy class as audit/: gitignored, user-local.

Why SQLite and not JSONL like audit/:
  * We need joins with future trade outcomes — relational queries.
  * Calibration metrics are slice-and-dice (per-provider, per-regime,
    per-confidence-bucket). SQL is the right shape.
  * One file, no server, trivially backup-able.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .lib import audit

DB_PATH = Path(__file__).resolve().parent.parent / "decisions.db"


# Schema kept deliberately minimal for Phase 1. Outcome columns are
# nullable placeholders — the reconciler in a later phase will populate
# them by joining against trade history from TV.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    request_id    TEXT PRIMARY KEY,
    ts            REAL NOT NULL,       -- unix seconds
    iso_ts        TEXT NOT NULL,       -- human-readable, local tz
    symbol        TEXT NOT NULL,
    mode          TEXT NOT NULL,       -- 'single' | 'deep'
    tf            TEXT,                -- timeframe for single-TF; null for deep
    optimal_tf    TEXT,                -- deep mode's picked TF; null otherwise
    timeframes    TEXT,                -- JSON array for deep; null for single
    provider      TEXT NOT NULL,       -- 'ollama' | 'claude_web' | 'anthropic'
    model         TEXT NOT NULL,
    signal        TEXT,                -- 'Long' | 'Short' | 'Skip'
    confidence    INTEGER,             -- 0..100
    entry         REAL,
    stop          REAL,
    tp            REAL,
    rationale     TEXT,
    pine_path     TEXT,                -- path to saved Pine; null if none
    usage_in      INTEGER,             -- input tokens (0 for claude_web)
    usage_out     INTEGER,             -- output tokens (0 for claude_web)
    cost_usd      REAL,
    elapsed_s     REAL,
    llm_elapsed_s REAL,

    -- Outcome columns — populated later by the reconciler job.
    -- NULL means "not yet reconciled," distinct from "reconciled and
    -- found nothing" (which is outcome = 'no_fill').
    outcome       TEXT,                -- 'hit_tp'|'hit_stop'|'expired'|'no_fill'|'flattened'|'skip_right'|'skip_wrong'
    realized_r    REAL,                -- P&L in R-multiples
    closed_at     REAL,                -- unix seconds

    -- Phase 5: trader's reflection after the outcome. One line, free
    -- text. NULL until the trader writes something.
    learning_note TEXT
);

CREATE INDEX IF NOT EXISTS ix_decisions_ts       ON decisions(ts);
CREATE INDEX IF NOT EXISTS ix_decisions_symbol   ON decisions(symbol);
CREATE INDEX IF NOT EXISTS ix_decisions_provider ON decisions(provider);
CREATE INDEX IF NOT EXISTS ix_decisions_outcome  ON decisions(outcome);
"""


def _connect() -> sqlite3.Connection:
    """Open a connection with WAL enabled (cheap concurrent readers).
    `isolation_level=None` → autocommit, so each log_decision call
    is its own transaction. We're doing one insert per call; no batching
    value to squeeze out, and autocommit keeps the semantics simple."""
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")  # WAL + NORMAL is the
                                              # canonical single-writer
                                              # safety/speed tradeoff
    return con


def init_db() -> None:
    """Create table + indexes if missing. Safe to call on every import.

    Also applies any forward-compatible schema migrations — we run
    `ALTER TABLE ADD COLUMN` statements that silently no-op when the
    column already exists. Keeps schema evolution in one place without
    requiring a migration tool."""
    con = _connect()
    try:
        con.executescript(_SCHEMA)
        # Migrations — each one is ALTER TABLE ADD COLUMN inside a
        # best-effort catch. SQLite raises on duplicate-column; that's
        # the expected signal that the migration already ran.
        for sql in (
            # Phase 5: trader's one-line takeaway after reviewing the
            # outcome.
            "ALTER TABLE decisions ADD COLUMN learning_note TEXT",
            # Path to the TradingView screenshot taken right AFTER the
            # pine overlay was applied — the "with levels drawn" image
            # used to rate setup quality and build a feedback loop.
            # Populated by ui_server's apply-pine endpoint; null until
            # the user clicks Apply pine to chart.
            "ALTER TABLE decisions ADD COLUMN applied_screenshot_path TEXT",
        ):
            try:
                con.execute(sql)
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
    finally:
        con.close()


def log_decision(result: dict[str, Any], request_id: str) -> None:
    """Insert a single decision row from an analyze_chart / analyze_deep
    result dict. `request_id` is passed separately because the result
    dict doesn't carry it (it lives in the audit contextvar).

    Any exception is caught and logged to the audit trail instead of
    raised — a broken DB must not break the analysis flow."""
    try:
        init_db()  # idempotent; cheap
        now = time.time()
        row = {
            "request_id":    request_id,
            "ts":            now,
            "iso_ts":        time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
            "symbol":        result.get("symbol"),
            "mode":          result.get("mode") or "single",
            "tf":            result.get("timeframe"),
            "optimal_tf":    result.get("optimal_tf"),
            "timeframes":    json.dumps(result["timeframes"]) if result.get("timeframes") else None,
            "provider":      result.get("provider") or "unknown",
            "model":         result.get("model") or "unknown",
            "signal":        result.get("signal"),
            "confidence":    _clamp_int(result.get("confidence"), 0, 100),
            "entry":         _to_float(result.get("entry")),
            "stop":          _to_float(result.get("stop")),
            "tp":            _to_float(result.get("tp")),
            "rationale":     result.get("rationale"),
            "pine_path":     result.get("pine_path"),
            "usage_in":      _to_int((result.get("usage") or {}).get("input_tokens")),
            "usage_out":     _to_int((result.get("usage") or {}).get("output_tokens")),
            "cost_usd":      _to_float(result.get("cost_usd")),
            "elapsed_s":     _to_float(result.get("elapsed_s")),
            "llm_elapsed_s": _to_float(result.get("llm_elapsed_s")),
        }
        con = _connect()
        try:
            # INSERT OR REPLACE because request_id is PRIMARY KEY. Repeat
            # writes for the same request_id (shouldn't happen but cheap
            # insurance) overwrite rather than crash.
            con.execute(
                """
                INSERT OR REPLACE INTO decisions (
                    request_id, ts, iso_ts, symbol, mode, tf, optimal_tf,
                    timeframes, provider, model, signal, confidence,
                    entry, stop, tp, rationale, pine_path,
                    usage_in, usage_out, cost_usd, elapsed_s, llm_elapsed_s
                ) VALUES (
                    :request_id, :ts, :iso_ts, :symbol, :mode, :tf, :optimal_tf,
                    :timeframes, :provider, :model, :signal, :confidence,
                    :entry, :stop, :tp, :rationale, :pine_path,
                    :usage_in, :usage_out, :cost_usd, :elapsed_s, :llm_elapsed_s
                )
                """,
                row,
            )
        finally:
            con.close()
        audit.log("decision_log.write", request_id=request_id,
                  symbol=row["symbol"], mode=row["mode"])
    except Exception as e:
        # Never let a logger failure break the analysis path. The audit
        # log is our escape valve: if decisions.db goes bad, we still
        # have the JSONL trail, and this event tells us the DB broke.
        audit.log("decision_log.write_fail",
                  error=f"{type(e).__name__}: {e}",
                  request_id=request_id)


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clamp_int(v: Any, lo: int, hi: int) -> int | None:
    n = _to_int(v)
    if n is None:
        return None
    return max(lo, min(hi, n))


# ---------------------------------------------------------------------------
# Read helpers — small, composable. The calibration endpoint / UI will
# build on these. Keeping them in this module avoids a separate query
# layer and the associated abstraction overhead.
# ---------------------------------------------------------------------------


def recent(limit: int = 50) -> list[dict]:
    """Return the most recent N decisions as dicts. For debugging / a
    minimal journal view before the full calibration chart ships."""
    init_db()
    con = _connect()
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM decisions ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def count() -> int:
    """Total decisions logged. Sanity check that the hook is firing."""
    init_db()
    con = _connect()
    try:
        return con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    finally:
        con.close()


def unreconciled(limit: int = 50) -> list[dict]:
    """Decisions that haven't had an outcome tagged yet, oldest first
    so the user reconciles chronologically (matters for sanity — if you
    reconcile the most recent first, you can't remember the older ones
    as well)."""
    init_db()
    con = _connect()
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM decisions WHERE outcome IS NULL "
            "ORDER BY ts ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def set_learning_note(request_id: str, note: str | None) -> bool:
    """Save/clear a trader's post-outcome reflection on a decision.
    Empty-string / None clears the note. Returns True if a row was
    matched.

    Independent of `set_outcome` — you can add/edit/clear the note at
    any time, before or after tagging the outcome. Separate setters
    keep the reconcile flow free of learning-note prompts (a busy end-
    of-day reconciler wants to move fast; reflection is a separate
    slower activity)."""
    init_db()
    con = _connect()
    try:
        clean = (note or "").strip() or None
        cur = con.execute(
            "UPDATE decisions SET learning_note = ? WHERE request_id = ?",
            (clean, request_id),
        )
        if cur.rowcount > 0:
            audit.log("decision_log.learning_note",
                      request_id=request_id,
                      note_len=len(clean) if clean else 0)
            return True
        return False
    finally:
        con.close()


def set_applied_screenshot(request_id: str, path: str) -> bool:
    """Save the path to the chart screenshot taken right AFTER the pine
    overlay was applied (the "with levels drawn" image). Lets the
    Journal tab / later review show the exact visual the trader saw
    when making the call, which is the highest-signal data for rating
    setup quality and building a feedback loop.

    Returns True on match, False if the request_id isn't in the table
    (e.g. an apply-pine that happened before the decision was logged —
    shouldn't happen in normal flow but worth distinguishing)."""
    init_db()
    con = _connect()
    try:
        cur = con.execute(
            "UPDATE decisions SET applied_screenshot_path = ? "
            "WHERE request_id = ?",
            (path, request_id),
        )
        if cur.rowcount > 0:
            audit.log("decision_log.applied_screenshot",
                      request_id=request_id, path=path)
            return True
        return False
    finally:
        con.close()


def set_outcome(request_id: str, outcome: str, realized_r: float | None,
                closed_at: float | None = None) -> bool:
    """Tag a decision with its realized outcome. Returns True on success,
    False if the request_id doesn't exist. Only the outcome columns are
    updated — decision data (signal, levels, rationale) is never
    mutated, so a mistaken tag can be re-run without losing the
    original call."""
    init_db()
    con = _connect()
    try:
        closed = closed_at if closed_at is not None else time.time()
        cur = con.execute(
            "UPDATE decisions SET outcome = ?, realized_r = ?, closed_at = ? "
            "WHERE request_id = ?",
            (outcome, realized_r, closed, request_id),
        )
        if cur.rowcount > 0:
            audit.log("decision_log.reconciled",
                      request_id=request_id, outcome=outcome,
                      realized_r=realized_r)
            return True
        return False
    finally:
        con.close()


def session_summary(since_ts: float | None = None) -> dict:
    """Aggregate decisions from `since_ts` (unix seconds) to now, or for
    the current local calendar day if since_ts is None.

    Returns a compact summary shape suitable for a header strip:
      total            — all decisions in window
      reconciled       — with an outcome tagged
      unreconciled     — no outcome yet
      wins             — realized_r > 0 (directional only)
      losses           — realized_r < 0
      skips            — signal == 'Skip' (regardless of reconciliation)
      realized_r_sum   — running R total across all closed directional trades
      overrides        — no_fill outcomes (AI said Long/Short, trader skipped)

    Pure read, zero side effects. Safe to call on every UI tick."""
    if since_ts is None:
        # Default: start of local-time day. Using local time matches how
        # traders think ("today" = this trading session, not UTC day).
        local = time.localtime()
        since_ts = time.mktime(time.struct_time((
            local.tm_year, local.tm_mon, local.tm_mday,
            0, 0, 0, 0, 0, local.tm_isdst,
        )))

    init_db()
    con = _connect()
    try:
        con.row_factory = sqlite3.Row
        row = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS reconciled,
                SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) AS unreconciled,
                SUM(CASE WHEN realized_r > 0 AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN realized_r < 0 AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN signal = 'Skip' THEN 1 ELSE 0 END) AS skips,
                SUM(CASE WHEN outcome != 'no_fill' THEN COALESCE(realized_r, 0) ELSE 0 END) AS realized_r_sum,
                SUM(CASE WHEN outcome = 'no_fill' THEN 1 ELSE 0 END) AS overrides
            FROM decisions
            WHERE ts >= ?
        """, (since_ts,)).fetchone()
        return {
            "since_ts":       since_ts,
            "total":          row["total"] or 0,
            "reconciled":     row["reconciled"] or 0,
            "unreconciled":   row["unreconciled"] or 0,
            "wins":           row["wins"] or 0,
            "losses":         row["losses"] or 0,
            "skips":          row["skips"] or 0,
            "realized_r_sum": row["realized_r_sum"] or 0.0,
            "overrides":      row["overrides"] or 0,
        }
    finally:
        con.close()


def rollup_summary(days: int = 7) -> dict:
    """N-day rollup for the Journal tab's weekly review panel.

    Richer than `session_summary` — adds per-provider R attribution, best
    and worst single-trade R for the window, and a comparison to the
    prior same-length window so drift is visible. Thesis's Phase 5.2:
    "P&L attribution: which setups worked, which providers drove
    winners/losers."

    Window: [now - days, now] for current; [now - 2·days, now - days]
    for prior. All times in local calendar days, midnight boundaries.
    """
    if days < 1:
        days = 1

    now = time.time()
    day_s = 86400
    # Align to local midnight so "last 7 days" means "last 7 calendar
    # days ending now" — matches how traders actually think, not a
    # rolling 168-hour window.
    local = time.localtime(now)
    midnight = time.mktime(time.struct_time((
        local.tm_year, local.tm_mon, local.tm_mday,
        0, 0, 0, 0, 0, local.tm_isdst,
    )))
    # Include the current day in the window, so N=7 covers today +
    # the prior 6 full days = 7 calendar days.
    cur_start = midnight - (days - 1) * day_s
    prior_start = cur_start - days * day_s
    prior_end = cur_start

    init_db()
    con = _connect()
    try:
        con.row_factory = sqlite3.Row
        def _window(t_start: float, t_end: float | None = None) -> dict:
            clause = "ts >= ?"
            params: tuple = (t_start,)
            if t_end is not None:
                clause += " AND ts < ?"
                params = (t_start, t_end)
            row = con.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS reconciled,
                    SUM(CASE WHEN realized_r > 0 AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN realized_r < 0 AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN outcome != 'no_fill' THEN COALESCE(realized_r, 0) ELSE 0 END) AS realized_r_sum,
                    MAX(CASE WHEN outcome != 'no_fill' THEN realized_r ELSE NULL END) AS best_r,
                    MIN(CASE WHEN outcome != 'no_fill' THEN realized_r ELSE NULL END) AS worst_r,
                    SUM(CASE WHEN outcome = 'no_fill' THEN 1 ELSE 0 END) AS overrides
                FROM decisions
                WHERE {clause}
            """, params).fetchone()
            return {k: (row[k] or 0) for k in row.keys()}

        current = _window(cur_start)
        prior = _window(prior_start, prior_end)

        # Per-provider R attribution within the window. Answers "which
        # AI made me money / lost me money this week?"
        per_provider = con.execute("""
            SELECT
                provider, model,
                COUNT(*) AS total,
                SUM(CASE WHEN outcome IS NOT NULL AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS closed,
                SUM(CASE WHEN realized_r > 0 AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN realized_r < 0 AND outcome != 'no_fill' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN outcome != 'no_fill' THEN COALESCE(realized_r, 0) ELSE 0 END) AS r_sum,
                AVG(CASE WHEN outcome != 'no_fill' THEN realized_r ELSE NULL END) AS r_avg
            FROM decisions
            WHERE ts >= ?
            GROUP BY provider, model
            ORDER BY r_sum DESC
        """, (cur_start,)).fetchall()

        return {
            "days": days,
            "cur_start_ts": cur_start,
            "prior_start_ts": prior_start,
            "now_ts": now,
            "current": current,
            "prior": prior,
            "per_provider": [dict(r) for r in per_provider],
        }
    finally:
        con.close()


def _bucket_for(confidence: int | None) -> str | None:
    """Return the confidence bucket label for a given raw confidence.
    Kept in sync with the SQL CASE in `calibration_summary`. Centralizing
    the boundary in Python means UI code never has to duplicate the
    bucketing logic."""
    if confidence is None:
        return None
    if confidence < 50:
        return "low (<50)"
    if confidence < 60:
        return "50-59"
    if confidence < 70:
        return "60-69"
    if confidence < 80:
        return "70-79"
    return "80+"


def bucket_track(provider: str, model: str, confidence: int | None
                 ) -> dict | None:
    """Historical track for the SPECIFIC (provider, model, bucket) of a
    pending decision. Returns `{n, hit_rate, avg_r, bucket}` or None if
    no matching reconciled decisions exist yet.

    This is the data for the inline "Sonnet track: 67% @ 70-79% (n=12)"
    chip shown beside each live confidence number. Embedding it in the
    analyze result (rather than a separate UI fetch) keeps the chip
    in sync with the decision it describes and avoids a race where the
    user reconciles between analyze and fetch."""
    bucket = _bucket_for(confidence)
    if bucket is None:
        return None
    init_db()
    con = _connect()
    try:
        con.row_factory = sqlite3.Row
        row = con.execute("""
            SELECT
                COUNT(*) AS n,
                AVG(CASE WHEN realized_r > 0 THEN 1.0 ELSE 0.0 END) AS hit_rate,
                AVG(realized_r) AS avg_r
            FROM decisions
            WHERE provider = ?
              AND model = ?
              AND outcome IS NOT NULL
              AND outcome != 'no_fill'
              AND signal IN ('Long', 'Short')
              AND confidence IS NOT NULL
              AND CASE
                    WHEN confidence < 50 THEN 'low (<50)'
                    WHEN confidence < 60 THEN '50-59'
                    WHEN confidence < 70 THEN '60-69'
                    WHEN confidence < 80 THEN '70-79'
                    ELSE '80+'
                  END = ?
        """, (provider, model, bucket)).fetchone()
        if row is None or row["n"] == 0:
            return {"n": 0, "hit_rate": None, "avg_r": None, "bucket": bucket}
        return {
            "n": row["n"],
            "hit_rate": row["hit_rate"],
            "avg_r": row["avg_r"],
            "bucket": bucket,
        }
    finally:
        con.close()


def calibration_summary() -> list[dict]:
    """Per-provider accuracy summary, grouped by confidence bucket.

    Returns rows like `{"provider": "claude_web", "model": "Sonnet 4.6",
    "bucket": "70-79", "n": 12, "hit_rate": 0.67, "avg_r": 0.8}`.
    Only counts decisions with a tagged outcome. This is the data that
    backs the eventual "Provider track: X% @ Y%" UI chip."""
    init_db()
    con = _connect()
    try:
        con.row_factory = sqlite3.Row
        # Single aggregate that returns BOTH calibration and override
        # metrics per bucket:
        #   n           — directional decisions with outcome != no_fill
        #                 (the denominator for hit_rate and avg_r)
        #   hit_rate    — fraction of those with realized_r > 0
        #   avg_r       — mean realized R over those
        #   n_total     — all directional decisions including no_fill
        #                 (the denominator for override_rate)
        #   n_overrides — directional signals that ended as no_fill
        #   override_rate — n_overrides / n_total (NULL when n_total = 0)
        #
        # Computing both in one query keeps the two metrics consistent
        # (they always share the same row source) and avoids a race
        # between two separate calls.
        rows = con.execute("""
            SELECT
                provider,
                model,
                CASE
                    WHEN confidence < 50 THEN 'low (<50)'
                    WHEN confidence < 60 THEN '50-59'
                    WHEN confidence < 70 THEN '60-69'
                    WHEN confidence < 80 THEN '70-79'
                    ELSE '80+'
                END AS bucket,
                SUM(CASE WHEN outcome != 'no_fill' THEN 1 ELSE 0 END) AS n,
                CAST(SUM(CASE WHEN outcome != 'no_fill' AND realized_r > 0 THEN 1 ELSE 0 END) AS REAL)
                    / NULLIF(SUM(CASE WHEN outcome != 'no_fill' THEN 1 ELSE 0 END), 0) AS hit_rate,
                AVG(CASE WHEN outcome != 'no_fill' THEN realized_r ELSE NULL END) AS avg_r,
                COUNT(*) AS n_total,
                SUM(CASE WHEN outcome = 'no_fill' THEN 1 ELSE 0 END) AS n_overrides,
                CAST(SUM(CASE WHEN outcome = 'no_fill' THEN 1 ELSE 0 END) AS REAL)
                    / NULLIF(COUNT(*), 0) AS override_rate
            FROM decisions
            WHERE outcome IS NOT NULL
              AND signal IN ('Long', 'Short')
              AND confidence IS NOT NULL
            GROUP BY provider, model, bucket
            ORDER BY provider, model, bucket
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
