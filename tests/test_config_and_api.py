"""Config + FastAPI route smoke tests (no Kokoro/torch required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oddbeaker_tts import __version__
from oddbeaker_tts.config import load_config, resolve_config_path
from oddbeaker_tts.engine import KokoroEngine, create_engine, reset_engine_singleton
from oddbeaker_tts import service as svc


@pytest.fixture(autouse=True)
def _reset_service_state(tmp_path, monkeypatch):
    reset_engine_singleton()
    svc._engine = None
    svc._config = {}
    svc._config_path_cli = None
    cache = tmp_path / "cache"
    cache.mkdir()
    svc._cache_dir = cache
    yield
    reset_engine_singleton()
    svc._engine = None
    svc._config = {}


def test_version():
    assert __version__ == "0.1.0"


def test_load_config_defaults_and_file(tmp_path):
    cfg_path = tmp_path / "tts.json"
    cfg_path.write_text(
        json.dumps(
            {
                "engine": "kokoro",
                "default_voice": "am_adam",
                "cache_enabled": False,
                "voices": [{"id": "am_adam", "label": "Adam", "gender": "male", "accent": "american"}],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg["default_voice"] == "am_adam"
    assert cfg["cache_enabled"] is False
    assert cfg["voices"][0]["id"] == "am_adam"
    assert resolve_config_path(cfg_path) == cfg_path


def test_create_engine_unknown():
    reset_engine_singleton()
    with pytest.raises(ValueError, match="Unknown"):
        create_engine("nope", singleton=False)


def test_kokoro_list_voices_without_model():
    eng = KokoroEngine(voices=[{"id": "af_heart", "label": "Heart", "gender": "female", "accent": "american"}])
    assert eng.list_voices()[0]["id"] == "af_heart"
    info = eng.get_info()
    assert info["name"] == "kokoro"
    assert "device" in info


def test_health_without_engine():
    svc.configure()
    client = TestClient(svc.app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engine_loaded"] is False


def test_synthesize_nothing_to_speak():
    svc.configure()
    client = TestClient(svc.app)
    # Empty-ish after preprocess: only whitespace
    r = client.post("/synthesize", json={"text": "   \n\n  "})
    assert r.status_code == 200
    body = r.json()
    assert body.get("reason") == "nothing_to_speak" or body.get("audio_url") is None


def test_synthesize_raw_uses_stub_engine(monkeypatch, tmp_path):
    """Inject a fake engine so /synthesize works without Kokoro."""

    class FakeEngine:
        def synthesize(self, text, voice_id, speed=1.0):
            # Minimal valid WAV header-ish payload is not required for cache write;
            # write tiny bytes and mock soundfile on cache hit path separately.
            return b"RIFF....WAVEfmt ", 0.5

        def list_voices(self):
            return [{"id": "af_heart", "label": "Heart", "gender": "female", "accent": "american"}]

        def get_info(self):
            return {"name": "fake", "device": "cpu", "vram_mb": 0}

    svc.configure(cache_dir=tmp_path / "c")
    svc._config["cache_enabled"] = True
    svc._config["default_voice"] = "af_heart"
    svc._engine = FakeEngine()

    client = TestClient(svc.app)
    r = client.post(
        "/synthesize",
        json={"text": "Hello world.", "raw": True, "voice": "af_heart"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is False
    assert body["duration_ms"] == 500
    assert body["text_spoken"] == "Hello world."
    assert body["audio_url"].startswith("/tts/")
    assert (svc._cache_dir / Path(body["audio_url"]).name).is_file()

    r2 = client.get("/voices")
    assert r2.status_code == 200
    assert r2.json()["voices"][0]["id"] == "af_heart"

    r3 = client.get("/info")
    assert r3.status_code == 200
    assert r3.json()["name"] == "fake"

    r4 = client.get("/health")
    assert r4.json()["engine_loaded"] is True
