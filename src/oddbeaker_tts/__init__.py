"""oddbeaker-tts — shared Kokoro TTS engine, preprocess, and HTTP service."""

from oddbeaker_tts.engine import KokoroEngine, TtsEngine, create_engine
from oddbeaker_tts.preprocess import build_spoken_text, clean_line_for_speech, expand_units

__version__ = "0.1.0"

__all__ = [
    "TtsEngine",
    "KokoroEngine",
    "create_engine",
    "build_spoken_text",
    "clean_line_for_speech",
    "expand_units",
    "__version__",
]
