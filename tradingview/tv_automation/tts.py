"""Text-to-speech via the local Qwen3-TTS sidecar.

The actual MLX model lives in a separate venv (1runapp/qwen3-tts-venv)
and is fronted by `tradingview/tts_sidecar.py`. This module is just an
async httpx client into that sidecar plus the forecast→narration text
distillation. Boot the sidecar with:

    ./start_qwen3_tts.sh

If the sidecar is down, `synthesize` raises `TTSUnavailable` and the
calling endpoint returns 503 with an actionable hint.

Why split this way: keeps mlx/mlx-audio/torch out of IntelligenceOS's
own .venv (avoids playwright/openai/anthropic version conflicts) and
lets the model stay warm across uvicorn `--reload` cycles in dev.
"""

from __future__ import annotations

import os

import httpx

from .lib import audit


SIDECAR_URL = os.environ.get("QWEN3_TTS_URL", "http://127.0.0.1:8790")
DEFAULT_VOICE = os.environ.get("QWEN3_TTS_DEFAULT_VOICE", "Sophia")
# First call after sidecar boot can take ~30-60s to load the bf16 1.7B
# model into MLX. Once warm, generate is bounded by audio duration.
SYNTH_TIMEOUT = float(os.environ.get("QWEN3_TTS_TIMEOUT", "120"))


class TTSUnavailable(RuntimeError):
    """Sidecar is unreachable or returned a fatal error."""


async def synthesize(text: str, voice: str | None = None) -> bytes:
    """Render `text` to a 24 kHz PCM WAV byte string.

    Raises TTSUnavailable if the sidecar isn't running. Other failures
    bubble up as RuntimeError with the sidecar's detail message."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")
    voice = voice or DEFAULT_VOICE
    audit.log("tts.synth.start", chars=len(text), voice=voice, sidecar=SIDECAR_URL)
    try:
        async with httpx.AsyncClient(timeout=SYNTH_TIMEOUT) as client:
            r = await client.post(
                f"{SIDECAR_URL}/speak",
                json={"text": text, "voice": voice},
            )
    except httpx.ConnectError as e:
        audit.log("tts.synth.unavailable", error=str(e))
        raise TTSUnavailable(
            f"qwen3-tts sidecar not reachable at {SIDECAR_URL} — start with ./start_qwen3_tts.sh"
        ) from e
    except httpx.RequestError as e:
        audit.log("tts.synth.error", error=str(e))
        raise TTSUnavailable(f"qwen3-tts sidecar error: {e}") from e

    if r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        audit.log("tts.synth.fail", status=r.status_code, detail=detail)
        raise RuntimeError(f"qwen3-tts sidecar HTTP {r.status_code}: {detail}")

    audit.log(
        "tts.synth.done",
        chars=len(text),
        voice=voice,
        bytes=len(r.content),
        audio_seconds=r.headers.get("X-TTS-Audio-Seconds"),
        synth_seconds=r.headers.get("X-TTS-Synth-Seconds"),
        rtf=r.headers.get("X-TTS-RTF"),
    )
    return r.content


async def synthesize_stream(text: str, voice: str | None = None):
    """Async generator yielding raw int16 PCM chunks at 24 kHz.

    The qwen3-tts sidecar currently exposes only the full-synth /speak
    endpoint (returns a complete 24 kHz mono int16 WAV). The old
    /speak/stream path is gone, which used to feed the browser
    progressively in ~3s. For now we synthesize the whole utterance,
    strip the WAV header, and yield the PCM in 8 KB chunks so the
    Web Audio consumer in the UI stays unchanged. First audio arrives
    after full synth (~10s for a typical 600-char forecast) instead of
    incrementally — acceptable trade-off until the sidecar regains a
    streaming endpoint."""
    wav = await synthesize(text, voice=voice)
    voice = voice or DEFAULT_VOICE
    # Walk the WAV chunks until we find "data" — header is usually 44
    # bytes, but extra chunks (LIST/INFO from some encoders) push it
    # further. find() handles both.
    idx = wav.find(b"data")
    if idx < 0:
        raise RuntimeError("WAV from sidecar has no 'data' chunk")
    pcm = wav[idx + 8:]  # skip "data" tag (4) + size field (4)
    audit.log("tts.stream.start", chars=len(text), voice=voice,
              sidecar=SIDECAR_URL, pcm_bytes=len(pcm))
    chunk_size = 8192
    for i in range(0, len(pcm), chunk_size):
        yield pcm[i:i + chunk_size]
    audit.log("tts.stream.done", chars=len(text), voice=voice)


async def list_voices() -> list[str]:
    """Read the registered clone names from the sidecar."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{SIDECAR_URL}/health")
            r.raise_for_status()
            return r.json().get("voices") or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Forecast → narration script.
# ---------------------------------------------------------------------------

_STAGE_LABELS = {
    "pre_session": "Pre-session",
    "1000": "Ten A M live",
    "1200": "Twelve P M live",
    "1400": "Two P M live",
    "reconciliation": "End of day reconciliation",
    "pre_session_reconciliation": "Pre-session reconciliation",
}


def forecast_script(forecast_json: dict, stage: str, date: str) -> str:
    """Distill a forecast JSON into a ~30-second spoken script.

    Reads the structured fields, not the markdown — sidesteps the
    smart-quote/em-dash gotchas that bite the claude_web pipeline."""
    j = forecast_json or {}
    parts: list[str] = []

    label = _STAGE_LABELS.get(stage, stage.replace("_", " "))
    parts.append(f"{label} forecast for {date}.")

    pred = j.get("predictions") or {}
    direction = pred.get("direction")
    conf = pred.get("direction_confidence") or pred.get("confidence")
    if direction:
        line = f"Direction: {direction}"
        if conf:
            line += f", confidence {conf}"
        parts.append(line + ".")

    goat = j.get("probable_goat") or {}
    if goat.get("direction") and goat.get("rationale"):
        win = goat.get("time_window") or ""
        parts.append(f"Probable goat: {goat['direction']} {win}. {goat['rationale']}".rstrip())

    tac = j.get("tactical_bias") or {}
    if tac.get("bias"):
        parts.append(f"Tactical bias: {tac['bias'].replace('_', ' ')}.")
    if tac.get("invalidation"):
        parts.append(f"Invalidation: {tac['invalidation']}")

    canary = j.get("canary") or {}
    if canary.get("thesis_summary"):
        parts.append(f"Canary thesis: {canary['thesis_summary']}")

    grading = j.get("grading") or j.get("scoring") or {}
    if grading.get("summary"):
        parts.append(f"Grading: {grading['summary']}")

    return " ".join(p for p in parts if p)
