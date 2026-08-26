# oddbeaker-tts

Standalone **Kokoro TTS** toolkit and HTTP service.

- **Package:** `oddbeaker-tts`
- **Import:** `oddbeaker_tts`
- **CLI:** `oddbeaker-tts` / `ob-tts`
- **Default bind:** `127.0.0.1:9201`
- **License:** Apache-2.0

Use it as a library (preprocess + engine) or run the FastAPI daemon for `POST /synthesize` and related routes.

## Features

- Kokoro-82M synthesis via Hugging Face Hub (`hexgrad/Kokoro-82M`)
- Markdown/LLM text cleanup for natural speech
- WAV cache with size cap
- Voice catalog (American / British, male / female defaults)
- HTTP API compatible with common local TTS glue (`POST /synthesize`, `GET /voices`, `GET /health`, `GET /info`, `GET /tts/{file}`)

## Layout

```
oddbeaker-tts/
  install.sh                   # one-shot installer (Linux + macOS best-effort)
  pyproject.toml
  README.md
  LICENSE
  etc/tts.json                 # example config
  etc/systemd/oddbeaker-tts.service
  src/oddbeaker_tts/
    __init__.py                # public API
    config.py                  # env + file loading
    engine.py                  # TtsEngine ABC + KokoroEngine
    preprocess.py              # markdown/LLM → speech text
    service.py                 # FastAPI app + CLI
    data/tts.json              # packaged default catalog
  tests/
```

## Quick install (recommended)

One script handles clone (or reuse), venv, runtime deps, model cache, config defaults (`127.0.0.1:9201`, voice `af_heart`), a user service, health check, and a sample synthesize smoke test.

**From a clone:**

```bash
git clone https://github.com/OddbeakerLLC/oddbeaker-tts.git
cd oddbeaker-tts
./install.sh
```

**Curl | bash** (no prior clone):

```bash
curl -fsSL https://raw.githubusercontent.com/OddbeakerLLC/oddbeaker-tts/main/install.sh | bash
```

Safe to re-run. If something is already healthy on port `9201`, the installer leaves that process alone (it will not kill a live service on another checkout such as a shared host daemon).

### After install — start / stop / status

**Linux (systemd user unit + linger):**

```bash
systemctl --user start oddbeaker-tts.service
systemctl --user stop oddbeaker-tts.service
systemctl --user restart oddbeaker-tts.service
systemctl --user status oddbeaker-tts.service
journalctl --user -u oddbeaker-tts.service -f
# survive logout/reboot:
loginctl enable-linger "$USER"
```

**macOS (LaunchAgent, best-effort):** `install.sh` writes `~/Library/LaunchAgents/com.oddbeaker.tts.plist`. Logs under `~/Library/Logs/oddbeaker-tts/`.

**Health / sample request:**

```bash
curl -sS http://127.0.0.1:9201/health
curl -sS -H 'Content-Type: application/json' \
  -d '{"text":"Hello","voice":"af_heart"}' \
  http://127.0.0.1:9201/synthesize
```

### Installer options

| Env / flag | Meaning |
|------------|---------|
| `ODDBEAKER_TTS_DIR` / `--dir` | Install root (default `~/.local/share/oddbeaker-tts`; in-tree `./install.sh` uses the checkout) |
| `ODDBEAKER_TTS_SOURCE` / `--source` | Local path or git URL |
| `ODDBEAKER_TTS_REF` / `--ref` | Git ref when cloning (default `main`) |
| `ODDBEAKER_TTS_HOST` / `--host` | Bind host (default `127.0.0.1`) |
| `ODDBEAKER_TTS_PORT` / `--port` | Bind port (default `9201`) |
| `ODDBEAKER_TTS_VOICE` / `--voice` | Default voice in `etc/tts.json` (default `af_heart`) |
| `ODDBEAKER_TTS_CACHE_DIR` | WAV cache (default `~/.cache/oddbeaker-tts`) |
| `--no-start` | Install only; do not start the daemon |
| `--no-smoke` | Skip synthesize smoke test |
| `--force-restart` | Bounce **this** tree's managed unit even if healthy (refuses if another WorkingDirectory owns the port) |

Default install layout: code under `ODDBEAKER_TTS_DIR`, user unit `oddbeaker-tts.service`, config `etc/tts.json`.

### Manual / dev install

Lightweight (preprocess + API tests; no model):

```bash
git clone https://github.com/OddbeakerLLC/oddbeaker-tts.git
cd oddbeaker-tts
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Full runtime (synthesis) without the installer:

```bash
pip install -e ".[dev,runtime]"
# Prefer a torch build that matches your machine, e.g. CPU:
#   pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m spacy download en_core_web_sm   # used by Kokoro / phonemizer path
```

**Model download:** first start pulls `hexgrad/Kokoro-82M` via Hugging Face Hub (~hundreds of MB). CI without network should run unit tests only (no service preload). Offline hosts need a pre-warmed HF cache; the service can run with `HF_HUB_OFFLINE=1`.

## Configuration

| Source | Purpose |
|--------|---------|
| `ODDBEAKER_TTS_CONFIG` | Path to `tts.json` |
| `--config PATH` | Same (CLI) |
| `./tts.json` | CWD fallback |
| packaged `data/tts.json` | Built-in defaults |
| `ODDBEAKER_TTS_CACHE_DIR` | WAV cache (default: `~/.cache/oddbeaker-tts`) |
| `ODDBEAKER_TTS_HOST` / `ODDBEAKER_TTS_PORT` | Bind address (default `127.0.0.1:9201`) |

Example `tts.json`:

```json
{
  "engine": "kokoro",
  "default_voice": "af_heart",
  "cache_enabled": true,
  "cache_max_mb": 200,
  "voices": [ ]
}
```

See `etc/tts.json` for a full voice catalog example.

## Run the service

```bash
oddbeaker-tts
# or
oddbeaker-tts --host 127.0.0.1 --port 9201 --config /path/to/tts.json
# skip model warm-up (first request pays load cost):
oddbeaker-tts --no-preload
```

### Library use

```python
from oddbeaker_tts import create_engine, build_spoken_text

spoken = build_spoken_text("**Hello** — 56°F outside.")
engine = create_engine("kokoro")
wav_bytes, duration_s = engine.synthesize(spoken, "af_heart")
```

## HTTP API

### `POST /synthesize`

```json
{ "text": "Hello **world**", "voice": "af_heart", "speed": 1.0, "raw": false }
```

Response:

```json
{
  "audio_url": "/tts/<hash>.wav",
  "duration_ms": 1200,
  "text_spoken": "Hello world",
  "cached": false,
  "gen_time_ms": 180
}
```

If preprocess yields nothing: `audio_url: null`, `reason: "nothing_to_speak"`.

### `GET /tts/{filename}`

Serves cached WAV (`audio/wav`).

### `GET /voices`

```json
{ "voices": [ { "id": "af_heart", "label": "Heart", "gender": "female", "accent": "american" }, ... ] }
```

### `GET /health`

```json
{ "status": "ok", "engine_loaded": true }
```

### `GET /info`

```json
{ "name": "kokoro", "model": "Kokoro-82M", "version": "0.9.4", "device": "cuda|cpu", "vram_mb": 0 }
```

## Voices (default catalog)

| ID | Label | Gender | Accent |
|----|-------|--------|--------|
| `af_heart` | Heart | female | american |
| `af_bella` | Bella | female | american |
| `am_adam` | Adam | male | american |
| `am_michael` | Michael | male | american |
| `bf_emma` | Emma | female | british |
| `bf_isabella` | Isabella | female | british |
| `bm_george` | George | male | british |
| `bm_daniel` | Daniel | male | british |

Default voice: **`af_heart`**.

## Systemd

`./install.sh` installs a **systemd user unit** (`oddbeaker-tts.service`) and tries `loginctl enable-linger` so the daemon survives logout/reboot.

For a hand-rolled system unit, see `etc/systemd/oddbeaker-tts.service` (template — set User, paths, and venv).

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
systemctl --user enable --now oddbeaker-tts.service
journalctl --user -u oddbeaker-tts.service -f
loginctl enable-linger "$USER"
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Kokoro / model weights and third-party packages remain under their own licenses.
