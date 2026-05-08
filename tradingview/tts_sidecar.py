"""Qwen3-TTS sidecar — runs in the 1runapp MLX venv, not IntelligenceOS's.

Boot:
    ./start_qwen3_tts.sh
which activates `~/Library/Application Support/1runapp/qwen3-tts-venv/`
and runs this module under that interpreter so `mlx_audio.tts.models.qwen3_tts`
resolves.

Why a sidecar: the MLX Qwen3-TTS stack (~3GB bf16 weights, mlx, mlx-audio,
qwen_tts) has different version pins than IntelligenceOS's Playwright/
OpenAI/Anthropic deps. Disjoint venvs avoid the conflict; localhost HTTP
is the integration boundary. The model also loads once and stays warm
across IntelligenceOS uvicorn reloads, which the in-process approach
cannot offer.

Endpoints:
    GET  /health         -> {"ok": true, "model_loaded": bool, "voices": [...]}
    POST /speak          -> audio/wav, body {"text", "voice"?}
                            voice = clone name from clones.json
                                    (default: Sophia)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel


CLONES_DIR = Path(os.environ.get(
    "QWEN3_TTS_CLONES_DIR",
    str(Path.home() / "Library" / "Application Support" / "1runapp" / "qwen3-tts-clones"),
))
CLONES_JSON = CLONES_DIR / "clones.json"
DEFAULT_MODEL = os.environ.get(
    "QWEN3_TTS_MODEL",
    # Base variant — supports ICL voice cloning via ref_audio+ref_text.
    # The CustomVoice variant is locked to its 9 built-in speakers and
    # rejects ref_audio at the dispatch level, so we don't use it here.
    "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
)
DEFAULT_VOICE = os.environ.get("QWEN3_TTS_DEFAULT_VOICE", "Sophia")
# Built-in speaker names supported by the Base model (case-insensitive).
# Users hitting one of these get the canonical voice instead of trying
# to look it up in clones.json.
_BUILTIN_SPEAKERS = {
    "serena", "vivian", "uncle_fu", "ryan", "aiden",
    "ono_anna", "sohee", "eric", "dylan",
}
STREAM_INTERVAL = float(os.environ.get("QWEN3_TTS_STREAM_INTERVAL", "2.0"))


_state: dict[str, Any] = {"model": None, "load_started_at": None, "load_done_at": None}
_load_lock = threading.Lock()


def _load_clones() -> dict[str, dict]:
    if not CLONES_JSON.exists():
        return {}
    try:
        return json.loads(CLONES_JSON.read_text())
    except Exception:
        return {}


def _ensure_model() -> None:
    if _state["model"] is not None:
        return
    with _load_lock:
        if _state["model"] is not None:
            return
        from mlx_audio.tts.models.qwen3_tts import Model

        _state["load_started_at"] = time.time()
        print(f"[qwen3-tts] loading {DEFAULT_MODEL} ...", flush=True)
        _state["model"] = Model.from_pretrained(DEFAULT_MODEL)
        _state["load_done_at"] = time.time()
        dur = _state["load_done_at"] - _state["load_started_at"]
        print(f"[qwen3-tts] loaded in {dur:.1f}s", flush=True)


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None


def _resolve_voice(voice: str, clones: dict) -> dict[str, Any]:
    gen_kwargs: dict[str, Any] = {}
    if voice in clones:
        clone = clones[voice]
        ref_audio = clone.get("ref_audio_path")
        ref_text = clone.get("ref_text") or None
        if not ref_audio or not Path(ref_audio).exists():
            raise HTTPException(500, f"voice '{voice}' ref_audio missing: {ref_audio}")
        gen_kwargs["ref_audio"] = ref_audio
        gen_kwargs["ref_text"] = ref_text
    elif voice.lower() in _BUILTIN_SPEAKERS:
        gen_kwargs["voice"] = voice.lower()
    else:
        raise HTTPException(
            404,
            f"voice '{voice}' not found — clones: {sorted(clones.keys())}; "
            f"builtins: {sorted(_BUILTIN_SPEAKERS)}",
        )
    return gen_kwargs


app = FastAPI(title="qwen3-tts-sidecar")


@app.get("/health")
def health() -> dict:
    clones = _load_clones()
    return {
        "ok": True,
        "model_id": DEFAULT_MODEL,
        "model_loaded": _state["model"] is not None,
        "default_voice": DEFAULT_VOICE,
        "voices": sorted(clones.keys()),
        "builtin_speakers": sorted(_BUILTIN_SPEAKERS),
        "load_seconds": (
            (_state["load_done_at"] - _state["load_started_at"])
            if _state["load_done_at"] else None
        ),
    }


@app.post("/speak")
def speak(req: SpeakRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")

    voice = req.voice or DEFAULT_VOICE
    gen_kwargs = _resolve_voice(voice, _load_clones())

    _ensure_model()
    model = _state["model"]

    t0 = time.time()
    chunks: list[np.ndarray] = []
    sample_rate = 24_000
    try:
        for result in model.generate(
            text=text,
            stream=True,
            streaming_interval=STREAM_INTERVAL,
            **gen_kwargs,
        ):
            sample_rate = result.sample_rate or sample_rate
            arr = np.asarray(result.audio, dtype=np.float32).squeeze()
            if arr.size:
                chunks.append(arr)
    except Exception as e:
        raise HTTPException(500, f"qwen3-tts generate failed: {e}")

    if not chunks:
        raise HTTPException(500, "qwen3-tts produced no audio")

    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    audio = np.clip(audio, -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, audio, samplerate=sample_rate, format="WAV", subtype="PCM_16")
    wav = buf.getvalue()
    dur_audio = len(audio) / sample_rate
    dur_synth = time.time() - t0
    rtf = dur_synth / max(dur_audio, 1e-6)
    print(
        f"[qwen3-tts] voice={voice} chars={len(text)} "
        f"audio={dur_audio:.1f}s synth={dur_synth:.2f}s rtf={rtf:.2f}",
        flush=True,
    )
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "X-TTS-Voice": voice,
            "X-TTS-Audio-Seconds": f"{dur_audio:.2f}",
            "X-TTS-Synth-Seconds": f"{dur_synth:.2f}",
            "X-TTS-RTF": f"{rtf:.3f}",
        },
    )


@app.post("/speak/stream")
def speak_stream(req: SpeakRequest):
    """Stream raw int16 PCM chunks as they're generated.

    First audio arrives within one streaming_interval (~2s of audio),
    so the caller can begin playback in ~3s instead of waiting for the
    full synthesis to complete."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")

    voice = req.voice or DEFAULT_VOICE
    gen_kwargs = _resolve_voice(voice, _load_clones())
    _ensure_model()
    model = _state["model"]

    def pcm_gen():
        sample_rate = 24_000
        t0 = time.time()
        total_samples = 0
        for result in model.generate(
            text=text,
            stream=True,
            streaming_interval=STREAM_INTERVAL,
            **gen_kwargs,
        ):
            sr = result.sample_rate or sample_rate
            sample_rate = sr
            arr = np.asarray(result.audio, dtype=np.float32).squeeze()
            if arr.size:
                pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
                total_samples += pcm.size
                yield pcm.tobytes()
        dur_audio = total_samples / sample_rate
        dur_synth = time.time() - t0
        print(
            f"[qwen3-tts] stream voice={voice} chars={len(text)} "
            f"audio={dur_audio:.1f}s synth={dur_synth:.2f}s "
            f"rtf={dur_synth / max(dur_audio, 1e-6):.2f}",
            flush=True,
        )

    return StreamingResponse(
        pcm_gen(),
        media_type="application/octet-stream",
        headers={"X-TTS-Sample-Rate": "24000", "X-TTS-Voice": voice},
    )


@app.exception_handler(404)
async def _404(request, exc):
    return JSONResponse({"detail": getattr(exc, "detail", "not found")}, status_code=404)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--preload", action="store_true", help="Load model at boot, not on first call")
    args = p.parse_args()
    if args.preload:
        _ensure_model()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
