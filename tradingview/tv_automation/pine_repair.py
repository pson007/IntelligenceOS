"""LLM-driven Pine repair loop.

When `apply_pine.py` reads Monaco compile errors via
`pine_compile.read_compile_summary`, today the only response is
"write a `compile_fail_*.txt` and quit." This module closes the loop:
feed the errors plus the failing source back to the LLM with a
constrained "repair-only" prompt, paste the fix, recompile. Up to N
attempts before giving up.

Pattern lifted from tradesdontlie/tradingview-mcp's `analyze()` static
checks + Monaco-marker reading: errors are GROUND TRUTH (Monaco
authoritative), so LLM repair is iterative until the marker list is
empty. Static pre-checks (array bounds, empty array, missing strategy
declaration) run first and short-circuit when they catch issues
without paying for an LLM call.

Usage:
    python -m tv_automation.pine_repair pine/generated/foo.pine
    python -m tv_automation.pine_repair pine/generated/foo.pine --max-attempts 3
    python -m tv_automation.pine_repair pine/generated/foo.pine --static-only

Driving the editor: the script writes the candidate to a temp .pine
file then invokes `apply_pine.py` as a subprocess (matching the
existing fire-and-forget pattern). Each attempt re-paste-saves and
re-reads markers, giving the LLM a deterministic feedback signal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .lib import audit


_REPAIR_ROOT = (Path(__file__).parent.parent / "pine" / "repair").resolve()


# Static checks — pattern-based pre-filters that catch common bugs
# without an LLM round-trip. Each check returns a list of diagnostic
# dicts compatible with Monaco's marker shape so callers can merge
# them with read_compile_summary's output.

_ARRAY_INDEX_RX = re.compile(r"array\.(get|set)\s*\(\s*(\w+)\s*,\s*(-?\d+)")
_FIRST_LAST_RX = re.compile(r"(\w+)\.(first|last)\s*\(\s*\)")
_STRATEGY_DECL_RX = re.compile(r"^\s*strategy\s*\(", re.MULTILINE)
_STRATEGY_CALL_RX = re.compile(r"\bstrategy\.(entry|close|exit)\s*\(")
_VERSION_RX = re.compile(r"//@version\s*=\s*(\d+)")


def static_analyze(source: str) -> list[dict]:
    """Catch obvious mistakes in Pine v6 source without invoking the
    compiler. Returns a list of `{severity_label, line, column, message}`
    in the same shape Monaco markers come back as. Empty list = clean."""
    issues: list[dict] = []
    lines = source.splitlines()

    # Version mismatch — repo convention is v6.
    vm = _VERSION_RX.search(source)
    if not vm:
        issues.append({
            "severity_label": "error", "line": 1, "column": 1,
            "message": "Missing `//@version=6` directive. CLAUDE.md "
                       "requires Pine v6 for this project.",
        })
    elif vm.group(1) != "6":
        line_no = source[:vm.start()].count("\n") + 1
        issues.append({
            "severity_label": "error", "line": line_no, "column": 1,
            "message": f"Pine v{vm.group(1)} declared; project standard "
                       "is v6. Update directive to `//@version=6`.",
        })

    # Negative array indices — Pine arrays don't support negative.
    for m in _ARRAY_INDEX_RX.finditer(source):
        idx = int(m.group(3))
        if idx < 0:
            line_no = source[:m.start()].count("\n") + 1
            issues.append({
                "severity_label": "error", "line": line_no, "column": 1,
                "message": f"Negative array index {idx} on `{m.group(2)}` — "
                           "Pine arrays use 0-based positive indices only.",
            })

    # `.first()` / `.last()` on something that's not provably non-empty.
    # Heuristic: complain only when there's NO `array.size(name)` guard
    # within 3 lines above the call site.
    for m in _FIRST_LAST_RX.finditer(source):
        line_no = source[:m.start()].count("\n") + 1
        var, method = m.group(1), m.group(2)
        guard_window = "\n".join(lines[max(0, line_no - 4):line_no - 1])
        if f"array.size({var})" not in guard_window:
            issues.append({
                "severity_label": "warning", "line": line_no, "column": 1,
                "message": f"`{var}.{method}()` without an `array.size({var})` "
                           "guard — runtime error if the array is empty.",
            })

    # `strategy.entry/close/exit` without a `strategy(...)` declaration.
    if _STRATEGY_CALL_RX.search(source) and not _STRATEGY_DECL_RX.search(source):
        issues.append({
            "severity_label": "error", "line": 1, "column": 1,
            "message": "`strategy.*` calls present but no `strategy(...)` "
                       "declaration. Either declare a strategy or remove "
                       "the calls (use `indicator(...)` instead).",
        })

    return issues


def _format_diagnostics(items: list[dict], max_show: int = 10) -> str:
    if not items:
        return "(no diagnostics)"
    out = []
    for d in items[:max_show]:
        out.append(
            f"  [{d.get('severity_label', '?')}] line "
            f"{d.get('line', '?')}:{d.get('column', '?')} — "
            f"{d.get('message', '')}"
        )
    if len(items) > max_show:
        out.append(f"  ... {len(items) - max_show} more")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# LLM repair prompt — kept narrow so the model rewrites code, not redesigns it.
# ---------------------------------------------------------------------------

_REPAIR_SYSTEM = """You are a Pine v6 repair specialist. The user will give you:
1. A Pine script that failed to compile
2. The exact diagnostics (line/column/message) Monaco reported

Your job: return ONLY the corrected Pine v6 source. No commentary,
no markdown fences, no diff format. The output must be the COMPLETE
script ready to paste into TradingView's Pine Editor.

Rules:
- Preserve the script's intent — fix syntax/semantics only, don't
  redesign the logic.
- Output must start with `//@version=6`.
- For `indicator(...)` scripts, keep `overlay=true` if it was already there.
- For `strategy(...)` scripts, keep all the original parameters
  (initial_capital, commission_type, etc.) — those affect backtests.
- If a diagnostic is ambiguous or you can't fix it without redesigning,
  output the original source unchanged. Don't invent random fixes."""


def _build_repair_user(source: str, diagnostics: list[dict]) -> str:
    return (
        "## DIAGNOSTICS (from TradingView's compiler)\n"
        + _format_diagnostics(diagnostics)
        + "\n\n## SOURCE\n```pine\n"
        + source
        + "\n```\n\nReturn the corrected Pine v6 source only."
    )


@dataclass
class RepairAttempt:
    attempt: int
    static_issues: list[dict]
    monaco_issues: list[dict]
    source_path: str
    repaired: bool
    repair_method: str  # "static" | "llm" | "no_change"


async def _call_llm_repair(source: str, diagnostics: list[dict]) -> str:
    """Drive the user's existing claude_web flow to repair the script.
    Returns the corrected source (raw text, no fences)."""
    from .claude_web import analyze_via_claude_web
    user = _build_repair_user(source, diagnostics)
    text, _, _ = await analyze_via_claude_web(
        # No image — pure text repair. analyze_via_claude_web takes
        # an image_path positionally; pass None and the prompt-only
        # path will be exercised. If that's not supported, callers
        # need to swap to a text-only entry point.
        None, _REPAIR_SYSTEM, user, model="Sonnet 4.6",
    )
    # Strip code fences if the model added them.
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:pine|pinescript)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip() + "\n"


# ---------------------------------------------------------------------------
# Apply driver — invokes apply_pine.py as a subprocess and reads its
# STDOUT for the compile summary. Mirrors the existing ui_server pattern.
# ---------------------------------------------------------------------------


async def _apply_and_read_diagnostics(pine_path: Path) -> dict:
    """Run apply_pine.py against `pine_path` and parse its output for
    Monaco diagnostics. Returns `{ok, errors, warnings, items, stdout}`.

    apply_pine writes a `compile_fail_*.txt` to pine/parse_failures
    when errors > 0, but doesn't expose the raw items list on stdout —
    we recover them by reading the failure dump if it exists."""
    apply_script = Path(__file__).parent.parent / "apply_pine.py"
    venv_py = Path(__file__).parent.parent / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable

    proc = await asyncio.create_subprocess_exec(
        py, str(apply_script), str(pine_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        cwd=str(apply_script.parent),
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    text = stdout.decode("utf-8", errors="replace")

    # apply_pine prints "Pine compiled clean" on success, "WARN: Pine
    # compiled with N error(s)" on failure. Parse the dump path out of
    # the WARN line so we can read the structured items.
    items: list[dict] = []
    errors = warnings = 0
    dump_match = re.search(r"Diagnostics:\s+(\S+)", text)
    if dump_match:
        dump_path = Path(dump_match.group(1))
        if dump_path.exists():
            dump_text = dump_path.read_text()
            head = dump_text.split("--- SOURCE ---")[0]
            errors_match = re.search(r"errors=(\d+)", head)
            warnings_match = re.search(r"warnings=(\d+)", head)
            if errors_match:
                errors = int(errors_match.group(1))
            if warnings_match:
                warnings = int(warnings_match.group(1))
            for m in re.finditer(
                r"\[(\w+)\] line (\d+):(\d+) — (.+)", head,
            ):
                items.append({
                    "severity_label": m.group(1),
                    "line": int(m.group(2)),
                    "column": int(m.group(3)),
                    "message": m.group(4),
                })

    return {
        "ok": proc.returncode == 0 and errors == 0,
        "errors": errors, "warnings": warnings, "items": items,
        "stdout": text[:2000],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def repair(
    pine_path: Path, *, max_attempts: int = 3,
    static_only: bool = False, llm_repairs: bool = True,
) -> list[RepairAttempt]:
    """Iterate static + Monaco repairs until clean (or attempts exhausted).

    `static_only=True` runs only the regex pre-checks and skips both
    apply and LLM. `llm_repairs=False` runs apply but doesn't auto-fix —
    use to GET diagnostics without invoking the LLM.
    Returns the per-attempt history."""
    _REPAIR_ROOT.mkdir(parents=True, exist_ok=True)
    history: list[RepairAttempt] = []
    source = pine_path.read_text()

    for attempt_idx in range(1, max_attempts + 1):
        # Step 1: static checks (cheap, no Monaco round-trip).
        static_issues = static_analyze(source)

        if static_only:
            history.append(RepairAttempt(
                attempt=attempt_idx, static_issues=static_issues,
                monaco_issues=[], source_path=str(pine_path),
                repaired=len(static_issues) == 0, repair_method="static",
            ))
            return history

        # Step 2: apply + read Monaco diagnostics.
        diags = await _apply_and_read_diagnostics(pine_path)
        monaco_items = diags["items"]
        all_issues = static_issues + monaco_items

        if not all_issues and diags["ok"]:
            history.append(RepairAttempt(
                attempt=attempt_idx, static_issues=[],
                monaco_issues=[], source_path=str(pine_path),
                repaired=True, repair_method="no_change",
            ))
            audit.log("pine_repair.clean", attempts=attempt_idx,
                      path=str(pine_path))
            return history

        if not llm_repairs:
            history.append(RepairAttempt(
                attempt=attempt_idx, static_issues=static_issues,
                monaco_issues=monaco_items, source_path=str(pine_path),
                repaired=False, repair_method="diagnose_only",
            ))
            return history

        # Step 3: ask the LLM for a repair.
        try:
            repaired = await _call_llm_repair(source, all_issues)
        except Exception as e:
            audit.log("pine_repair.llm_fail", attempt=attempt_idx, err=str(e))
            history.append(RepairAttempt(
                attempt=attempt_idx, static_issues=static_issues,
                monaco_issues=monaco_items, source_path=str(pine_path),
                repaired=False, repair_method="llm_error",
            ))
            return history

        if repaired == source:
            # Model returned no change — give up rather than loop.
            audit.log("pine_repair.no_change", attempt=attempt_idx)
            history.append(RepairAttempt(
                attempt=attempt_idx, static_issues=static_issues,
                monaco_issues=monaco_items, source_path=str(pine_path),
                repaired=False, repair_method="llm_no_change",
            ))
            return history

        # Save each attempt's intermediate so the operator can audit
        # what the LLM proposed at each step.
        attempt_path = _REPAIR_ROOT / f"{pine_path.stem}_attempt{attempt_idx}.pine"
        attempt_path.write_text(repaired)

        # Replace the original (apply_pine.py reads the file by path).
        pine_path.write_text(repaired)
        source = repaired
        history.append(RepairAttempt(
            attempt=attempt_idx, static_issues=static_issues,
            monaco_issues=monaco_items, source_path=str(attempt_path),
            repaired=False, repair_method="llm",
        ))

    audit.log("pine_repair.exhausted", attempts=max_attempts,
              path=str(pine_path))
    return history


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.pine_repair")
    p.add_argument("path", help="Path to .pine file to repair")
    p.add_argument("--max-attempts", type=int, default=3,
                   help="Max repair iterations (default 3)")
    p.add_argument("--static-only", action="store_true",
                   help="Run only static checks; skip apply + LLM")
    p.add_argument("--no-llm", action="store_true",
                   help="Diagnose only; don't invoke LLM repair")
    args = p.parse_args()

    pine_path = Path(args.path).expanduser().resolve()
    if not pine_path.exists():
        sys.exit(f"file not found: {pine_path}")

    history = asyncio.run(repair(
        pine_path, max_attempts=args.max_attempts,
        static_only=args.static_only, llm_repairs=not args.no_llm,
    ))
    out = [{
        "attempt": h.attempt,
        "static": len(h.static_issues),
        "monaco": len(h.monaco_issues),
        "repair_method": h.repair_method,
        "repaired": h.repaired,
        "source_path": h.source_path,
    } for h in history]
    print(json.dumps(out, indent=2))
    final = history[-1] if history else None
    sys.exit(0 if final and final.repaired else 1)


if __name__ == "__main__":
    _main()
