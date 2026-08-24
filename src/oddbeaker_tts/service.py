"""
oddbeaker-tts HTTP service — persistent Kokoro TTS daemon.

Keeps the Kokoro pipeline loaded so speech generation avoids cold-start latency.

Usage:
    oddbeaker-tts                     # default 127.0.0.1:9201
    oddbeaker-tts --port 9202
    ODDBEAKER_TTS_CONFIG=/path/tts.json oddbeaker-tts

API (compatible with Jobe jobe-tts-service):
    POST /synthesize    - Generate speech audio from text
    GET  /voices        - List available voices
    GET  /health        - Health check
    GET  /info          - Engine info (model, device, VRAM)
    GET  /tts/{file}    - Serve cached WAV
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from oddbeaker_tts.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    default_cache_dir,
    load_config,
)
from oddbeaker_tts.engine import KOKORO_REPO_ID, create_engine
from oddbeaker_tts.preprocess import build_spoken_text

logger = logging.getLogger("oddbeaker-tts")

# Set at process start via configure() / main()
_config: dict[str, Any] = {}
_cache_dir: Path = default_cache_dir()
_engine = None
_config_path_cli: str | None = None

app = FastAPI(title="Oddbeaker TTS Service", version="0.1.0")


class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    speed: float = 1.0
    raw: bool = False  # If true, skip preprocessing


def configure(
    *,
    config_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load config and set cache dir. Idempotent for service startup."""
    global _config, _cache_dir, _config_path_cli
    _config_path_cli = str(config_path) if config_path else None
    _config = load_config(config_path)
    if cache_dir is not None:
        _cache_dir = Path(cache_dir).expanduser()
    else:
        env_cache = os.environ.get("ODDBEAKER_TTS_CACHE_DIR")
        _cache_dir = Path(env_cache).expanduser() if env_cache else default_cache_dir()
    return _config


def get_config() -> dict[str, Any]:
    global _config
    if not _config:
        configure(config_path=_config_path_cli)
    return _config


def get_engine():
    global _engine
    if _engine is None:
        config = get_config()
        logger.info("Initializing TTS engine: %s", config.get("engine", "kokoro"))
        t0 = time.time()
        _engine = create_engine(
            config.get("engine"),
            voices=config.get("voices"),
            config=config,
            singleton=True,
        )
        logger.info("TTS engine loaded in %.1fs", time.time() - t0)
    return _engine


def get_cache_path(text: str, voice: str) -> Path:
    key = f"{text}|{voice}"
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return _cache_dir / f"{h}.wav"


def enforce_cache_limit() -> None:
    config = get_config()
    max_mb = config.get("cache_max_mb", 200)
    max_bytes = max_mb * 1024 * 1024

    if not _cache_dir.exists():
        return

    files = sorted(_cache_dir.glob("*.wav"), key=lambda f: f.stat().st_atime)
    total = sum(f.stat().st_size for f in files)

    while total > max_bytes and files:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink()
        logger.info("Cache evict: %s", oldest.name)


def _kokoro_model_cached() -> bool:
    """True if HuggingFace hub cache already has Kokoro config.json."""
    try:
        from huggingface_hub import try_to_load_from_cache

        path = try_to_load_from_cache(KOKORO_REPO_ID, "config.json")
        return bool(path) and path is not True and os.path.isfile(str(path))
    except Exception:
        roots = []
        hf_home = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
        if hf_home:
            roots.append(Path(hf_home))
        home = Path(os.environ.get("HOME", str(Path.home())))
        roots.append(home / ".cache" / "huggingface" / "hub")
        for root in roots:
            snap = root / f"models--{KOKORO_REPO_ID.replace('/', '--')}" / "snapshots"
            if not snap.is_dir():
                continue
            for cfg in snap.glob("*/config.json"):
                if cfg.is_file():
                    return True
        return False


def ensure_kokoro_model() -> None:
    """
    Ensure Kokoro weights are present before enabling HF offline mode.

    Fresh installs often have the kokoro pip package but an empty HF cache.
    HF_HUB_OFFLINE=1 then makes startup crash-loop forever.
    """
    if _kokoro_model_cached():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        return
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    logger.info("Kokoro model not in HF cache — downloading %s ...", KOKORO_REPO_ID)
    from huggingface_hub import snapshot_download

    path = snapshot_download(repo_id=KOKORO_REPO_ID)
    logger.info("Kokoro model ready at %s", path)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    """Generate speech audio from text."""
    config = get_config()
    voice = req.voice or config.get("default_voice", "af_heart")

    if req.raw:
        spoken_text = req.text
    else:
        spoken_text = build_spoken_text(req.text)
        if not spoken_text:
            return JSONResponse(
                {
                    "audio_url": None,
                    "duration_ms": 0,
                    "text_spoken": "",
                    "reason": "nothing_to_speak",
                }
            )

    cache_path = get_cache_path(spoken_text, voice)
    if config.get("cache_enabled", True) and cache_path.exists():
        import soundfile as sf

        info = sf.info(str(cache_path))
        duration_ms = int(info.duration * 1000)
        cache_path.touch()
        logger.info("Cache hit: %s (%sms)", cache_path.name, duration_ms)
        return {
            "audio_url": f"/tts/{cache_path.name}",
            "duration_ms": duration_ms,
            "text_spoken": spoken_text,
            "cached": True,
        }

    try:
        engine = get_engine()
        t0 = time.time()
        wav_bytes, duration = engine.synthesize(spoken_text, voice, req.speed)
        gen_time = time.time() - t0
        duration_ms = int(duration * 1000)

        logger.info(
            "Synthesized: %s chars → %.1fs audio in %.2fs (voice=%s)",
            len(spoken_text),
            duration,
            gen_time,
            voice,
        )

        if config.get("cache_enabled", True):
            _cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(wav_bytes)
            enforce_cache_limit()

        return {
            "audio_url": f"/tts/{cache_path.name}",
            "duration_ms": duration_ms,
            "text_spoken": spoken_text,
            "cached": False,
            "gen_time_ms": int(gen_time * 1000),
        }
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/tts/{filename}")
async def serve_audio(filename: str):
    """Serve cached audio files."""
    # Prevent path traversal
    if "/" in filename or "\\" in filename or not filename.endswith(".wav"):
        raise HTTPException(status_code=404, detail="Audio not found")
    path = (_cache_dir / filename).resolve()
    if not str(path).startswith(str(_cache_dir.resolve())) or not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/wav")


@app.get("/voices")
async def list_voices():
    """List available voices."""
    engine = get_engine()
    return {"voices": engine.list_voices()}


@app.get("/health")
async def health():
    """Health check (engine may still be lazy-loaded)."""
    return {"status": "ok", "engine_loaded": _engine is not None}


@app.get("/info")
async def info():
    """Engine info."""
    engine = get_engine()
    return engine.get_info()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Oddbeaker TTS Service")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ODDBEAKER_TTS_PORT", DEFAULT_PORT)),
        help=f"Port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("ODDBEAKER_TTS_HOST", DEFAULT_HOST),
        help=f"Host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("ODDBEAKER_TTS_CONFIG"),
        help="Path to tts.json (or set ODDBEAKER_TTS_CONFIG)",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("ODDBEAKER_TTS_CACHE_DIR"),
        help="WAV cache directory (or set ODDBEAKER_TTS_CACHE_DIR)",
    )
    parser.add_argument(
        "--no-preload",
        action="store_true",
        help="Skip model download check and pipeline warm-up (faster start; first request pays cost)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = configure(config_path=args.config, cache_dir=args.cache_dir)
    _cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"Oddbeaker TTS Service starting on {args.host}:{args.port}")
    print(f"  Cache dir: {_cache_dir}")
    print(f"  Config: {cfg.get('_config_path') or '(built-in defaults)'}")
    print(f"  Default voice: {cfg.get('default_voice')}")

    if not args.no_preload:
        ensure_kokoro_model()
        logger.info("Pre-loading TTS engine...")
        engine = get_engine()
        logger.info("Warming American English pipeline...")
        engine._get_pipeline("af_heart")  # type: ignore[attr-defined]
        logger.info("Warming British English pipeline (bf_emma)...")
        engine._get_pipeline("bf_emma")  # type: ignore[attr-defined]
        logger.info("TTS engine ready")

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
