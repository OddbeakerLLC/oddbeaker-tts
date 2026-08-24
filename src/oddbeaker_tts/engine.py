"""
TTS Engine Abstraction

Pluggable engine interface for text-to-speech synthesis.
Currently implements Kokoro (82M parameters, GPU or CPU).

Usage:
    engine = create_engine("kokoro", voices=config["voices"])
    audio_bytes, duration = engine.synthesize("Hello world", "af_heart")
    voices = engine.list_voices()
"""

from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import soundfile as sf

from oddbeaker_tts.config import DEFAULT_ENGINE, DEFAULT_VOICES, load_config

logger = logging.getLogger(__name__)

KOKORO_REPO_ID = "hexgrad/Kokoro-82M"


class TtsEngine(ABC):
    """Abstract base class for TTS engines."""

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, speed: float = 1.0) -> tuple[bytes, float]:
        """
        Synthesize speech from text.

        Returns:
            (wav_bytes, duration_seconds)
        """

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """Return list of available voices: [{id, label, gender, accent}]"""

    @abstractmethod
    def get_info(self) -> dict:
        """Return engine metadata: {name, version, device, vram_mb}"""


class KokoroEngine(TtsEngine):
    """Kokoro 82M TTS engine (GPU when available, else CPU)."""

    def __init__(self, voices: list[dict] | None = None, repo_id: str = KOKORO_REPO_ID):
        self._pipeline_a = None  # American English
        self._pipeline_b = None  # British English
        self._voices_config = list(voices) if voices is not None else list(DEFAULT_VOICES)
        self._repo_id = repo_id

    def _get_pipeline(self, voice_id: str):
        """Get or create the appropriate pipeline for a voice."""
        # Voice ID prefix determines language: a=American, b=British
        lang = voice_id[0] if voice_id else "a"

        if lang == "b":
            if self._pipeline_b is None:
                from kokoro import KPipeline

                logger.info("Loading Kokoro pipeline (British English)...")
                self._pipeline_b = KPipeline(lang_code="b", repo_id=self._repo_id)
                logger.info("Kokoro British pipeline loaded")
            return self._pipeline_b

        if self._pipeline_a is None:
            from kokoro import KPipeline

            logger.info("Loading Kokoro pipeline (American English)...")
            self._pipeline_a = KPipeline(lang_code="a", repo_id=self._repo_id)
            logger.info("Kokoro American pipeline loaded")
        return self._pipeline_a

    def synthesize(self, text: str, voice_id: str, speed: float = 1.0) -> tuple[bytes, float]:
        """Synthesize speech using Kokoro."""
        pipeline = self._get_pipeline(voice_id)

        chunks = []
        for _i, (_gs, _ps, audio) in enumerate(pipeline(text, voice=voice_id, speed=speed)):
            chunks.append(audio)

        if not chunks:
            return b"", 0.0

        full_audio = np.concatenate(chunks)
        duration = len(full_audio) / 24000

        buf = io.BytesIO()
        sf.write(buf, full_audio, 24000, format="WAV")
        return buf.getvalue(), duration

    def list_voices(self) -> list[dict]:
        return self._voices_config

    def get_info(self) -> dict:
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            vram = 0
            if device == "cuda":
                vram = int(torch.cuda.memory_allocated() / 1024 / 1024)
        except Exception:
            device = "unknown"
            vram = 0
        return {
            "name": "kokoro",
            "model": "Kokoro-82M",
            "version": "0.9.4",
            "device": device,
            "vram_mb": vram,
            "repo_id": self._repo_id,
        }


_engine_instance: TtsEngine | None = None


def create_engine(
    engine_name: str | None = None,
    *,
    voices: list[dict] | None = None,
    config: dict[str, Any] | None = None,
    singleton: bool = True,
) -> TtsEngine:
    """
    Create a TTS engine by name.

    Args:
        engine_name: Engine id (default from config or "kokoro")
        voices: Voice catalog override
        config: Pre-loaded config dict (avoids re-reading file)
        singleton: Reuse process-wide instance (service default)
    """
    global _engine_instance

    if singleton and _engine_instance is not None:
        return _engine_instance

    cfg = config if config is not None else load_config()
    name = engine_name or cfg.get("engine") or DEFAULT_ENGINE
    voice_list = voices if voices is not None else cfg.get("voices")

    if name == "kokoro":
        engine: TtsEngine = KokoroEngine(voices=voice_list)
    else:
        raise ValueError(f"Unknown TTS engine: {name}")

    if singleton:
        _engine_instance = engine
    return engine


def reset_engine_singleton() -> None:
    """Clear process-wide engine (tests / reload)."""
    global _engine_instance
    _engine_instance = None
