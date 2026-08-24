"""Configuration loading for oddbeaker-tts (env + optional JSON file)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Package-shipped config (installed) + repo etc/ copy for source checkouts
_PACKAGE_DIR = Path(__file__).resolve().parent
_PACKAGED_CONFIG = _PACKAGE_DIR / "data" / "tts.json"
_REPO_EXAMPLE_CONFIG = _PACKAGE_DIR.parent.parent / "etc" / "tts.json"

DEFAULT_VOICE = "af_heart"
DEFAULT_ENGINE = "kokoro"
DEFAULT_CACHE_MAX_MB = 200
DEFAULT_PORT = 9201
DEFAULT_HOST = "127.0.0.1"

DEFAULT_VOICES: list[dict[str, str]] = [
    {"id": "af_heart", "label": "Heart", "gender": "female", "accent": "american"},
    {"id": "af_bella", "label": "Bella", "gender": "female", "accent": "american"},
    {"id": "am_adam", "label": "Adam", "gender": "male", "accent": "american"},
    {"id": "am_michael", "label": "Michael", "gender": "male", "accent": "american"},
    {"id": "bf_emma", "label": "Emma", "gender": "female", "accent": "british"},
    {"id": "bf_isabella", "label": "Isabella", "gender": "female", "accent": "british"},
    {"id": "bm_george", "label": "George", "gender": "male", "accent": "british"},
    {"id": "bm_daniel", "label": "Daniel", "gender": "male", "accent": "british"},
]


def default_cache_dir() -> Path:
    """Resolve cache directory: ODDBEAKER_TTS_CACHE_DIR or XDG/cache fallback."""
    env = os.environ.get("ODDBEAKER_TTS_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "oddbeaker-tts"
    return Path.home() / ".cache" / "oddbeaker-tts"


def resolve_config_path(explicit: str | Path | None = None) -> Path | None:
    """
    Config search order:
      1. explicit path (CLI)
      2. ODDBEAKER_TTS_CONFIG env
      3. ./tts.json (cwd)
      4. package etc/tts.json (shipped example)
    Returns first existing path, or None.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("ODDBEAKER_TTS_CONFIG")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path.cwd() / "tts.json")
    if _PACKAGED_CONFIG.is_file():
        candidates.append(_PACKAGED_CONFIG)
    if _REPO_EXAMPLE_CONFIG.is_file():
        candidates.append(_REPO_EXAMPLE_CONFIG)

    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config(explicit: str | Path | None = None) -> dict[str, Any]:
    """Load TTS config dict with sensible defaults."""
    path = resolve_config_path(explicit)
    data: dict[str, Any] = {}
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.debug("Loaded TTS config from %s", path)
        except Exception as e:
            logger.warning("Failed to load TTS config from %s: %s", path, e)

    return {
        "engine": data.get("engine", DEFAULT_ENGINE),
        "default_voice": data.get("default_voice", DEFAULT_VOICE),
        "cache_enabled": data.get("cache_enabled", True),
        "cache_max_mb": int(data.get("cache_max_mb", DEFAULT_CACHE_MAX_MB)),
        "voices": data.get("voices") or list(DEFAULT_VOICES),
        "_config_path": str(path) if path else None,
    }
