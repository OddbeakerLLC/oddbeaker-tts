# oddbeaker-tts — Sitemap
_Last updated: 2026-08-24_

## Overview
Standalone open-source Kokoro TTS toolkit and HTTP service (Apache-2.0). General-purpose; consumed by Jobe AI, BizAgent, and others via HTTP or library import.

## Structure
```
oddbeaker-tts/                 # git root (standalone)
  pyproject.toml               # package oddbeaker-tts, Apache-2.0
  LICENSE
  README.md
  etc/tts.json
  etc/systemd/oddbeaker-tts.service
  src/oddbeaker_tts/
  tests/
  sitemap.md
  .agent/journal/
```

## Key Integrations
- **HTTP consumers:** Jobe AI, BizAgent (and any client) — `POST /synthesize` on port **9201**
- **Model:** `hexgrad/Kokoro-82M` via Hugging Face Hub + `kokoro` Python package
- **Config env:** `ODDBEAKER_TTS_CONFIG`, `ODDBEAKER_TTS_CACHE_DIR`, `ODDBEAKER_TTS_HOST`, `ODDBEAKER_TTS_PORT`
- **Live host (ai-trainer):** user systemd `oddbeaker-tts.service` → `127.0.0.1:9201`; code root `/home/bizagent/dev/oddbeaker-tts`

## Active Work
- Split complete from `oddbeaker-framework` monorepo into this standalone repo.
- Waiting on operator/hub for public GitHub remote URL (do not invent origin).
- Package v0.1.0; unit/API tests without model are the CI path.

## Known Issues
- Full synthesis needs `[runtime]` extras (`kokoro`, `torch`), spaCy `en_core_web_sm`, and HF Kokoro cache.
- On ai-trainer, WAV cache is `~/.cache/oddbeaker-tts` until root creates writable `/var/cache/oddbeaker-tts`.
- Host has no usable NVIDIA device for this process; service runs CPU torch.
- GitHub `origin` not configured yet.

## Remote
- `origin`: **unset** — ask hub/operator for GitHub URL, then:
  `git remote add origin <url> && git push -u origin master`
