#!/usr/bin/env bash
# oddbeaker-tts one-shot installer — Linux (primary) + macOS (best-effort).
#
# One-liner (from a clone):
#   ./install.sh
#
# Curl|bash (public repo):
#   curl -fsSL https://raw.githubusercontent.com/OddbeakerLLC/oddbeaker-tts/main/install.sh | bash
#
# What this does:
#   - clone or reuse an existing checkout
#   - Python venv + [runtime] deps (CPU torch when no NVIDIA GPU)
#   - spaCy en_core_web_sm (best-effort)
#   - config defaults (127.0.0.1:9201, voice af_heart)
#   - systemd --user unit + linger (Linux); launchd plist (macOS) or nohup fallback
#   - health check + sample synthesize smoke test
#   - print start/stop/status commands
#
# Safe to re-run. If something healthy is already on the target port, the
# installer does not kill or replace that process — it only refreshes the
# local tree/venv/unit when installing into a managed directory.
#
# Env (optional):
#   ODDBEAKER_TTS_DIR=path       Install root (default: ~/.local/share/oddbeaker-tts)
#   ODDBEAKER_TTS_SOURCE=path|url  Local tree or git URL (default: discover / GitHub)
#   ODDBEAKER_TTS_REF=ref        Git branch/tag when cloning (default: main)
#   ODDBEAKER_TTS_HOST=addr      Bind host (default: 127.0.0.1)
#   ODDBEAKER_TTS_PORT=port      Bind port (default: 9201)
#   ODDBEAKER_TTS_VOICE=id       Default voice written into config (default: af_heart)
#   ODDBEAKER_TTS_CACHE_DIR=path WAV cache (default: ~/.cache/oddbeaker-tts)
#   ODDBEAKER_TTS_NO_START=1     Install only; do not start the daemon
#   ODDBEAKER_TTS_NO_SMOKE=1     Skip synthesize smoke test
#   ODDBEAKER_TTS_FORCE_RESTART=1  Restart managed unit even if already healthy
#
# Flags:
#   --dir PATH          Same as ODDBEAKER_TTS_DIR
#   --source PATH|URL   Same as ODDBEAKER_TTS_SOURCE
#   --ref REF           Same as ODDBEAKER_TTS_REF
#   --host ADDR         Same as ODDBEAKER_TTS_HOST
#   --port N            Same as ODDBEAKER_TTS_PORT
#   --voice ID          Same as ODDBEAKER_TTS_VOICE
#   --no-start          Same as ODDBEAKER_TTS_NO_START=1
#   --no-smoke          Same as ODDBEAKER_TTS_NO_SMOKE=1
#   --force-restart     Same as ODDBEAKER_TTS_FORCE_RESTART=1
#   --yes|-y            Non-interactive (reserved; currently no prompts)
#   -h|--help           Show this header and exit
#
set -euo pipefail

# --- defaults ---
DIR="${ODDBEAKER_TTS_DIR:-}"
SOURCE="${ODDBEAKER_TTS_SOURCE:-}"
REF="${ODDBEAKER_TTS_REF:-main}"
HOST="${ODDBEAKER_TTS_HOST:-127.0.0.1}"
PORT="${ODDBEAKER_TTS_PORT:-9201}"
VOICE="${ODDBEAKER_TTS_VOICE:-af_heart}"
CACHE_DIR="${ODDBEAKER_TTS_CACHE_DIR:-}"
NO_START="${ODDBEAKER_TTS_NO_START:-0}"
NO_SMOKE="${ODDBEAKER_TTS_NO_SMOKE:-0}"
FORCE_RESTART="${ODDBEAKER_TTS_FORCE_RESTART:-0}"
YES=0

DEFAULT_GIT_HTTPS="https://github.com/OddbeakerLLC/oddbeaker-tts.git"
DEFAULT_GIT_SSH="ssh://git@github.com/OddbeakerLLC/oddbeaker-tts.git"
DEFAULT_GIT_SCP="git@github.com:OddbeakerLLC/oddbeaker-tts.git"
UNIT_NAME="oddbeaker-tts.service"
LAUNCHD_LABEL="com.oddbeaker.tts"

# --- presentation ---
BOLD=$'\033[1m'; DIM=$'\033[2m'
RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'
NC=$'\033[0m'

step() { printf "\n${BOLD}${BLUE}==>${NC} ${BOLD}%s${NC}\n" "$*"; }
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$*"; }
note() { printf "  ${DIM}%s${NC}\n" "$*"; }
warn() { printf "  ${YELLOW}!${NC} %s\n" "$*" >&2; }
die()  { printf "\n${RED}✗ %s${NC}\n\n" "$*" >&2; exit 1; }

usage() {
  sed -n '2,48p' "$0" | sed 's/^# \?//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) DIR="${2:-}"; shift 2 ;;
    --source) SOURCE="${2:-}"; shift 2 ;;
    --ref) REF="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --voice) VOICE="${2:-}"; shift 2 ;;
    --no-start) NO_START=1; shift ;;
    --no-smoke) NO_SMOKE=1; shift ;;
    --force-restart) FORCE_RESTART=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

# Normalize boolean-ish env
[[ "$NO_START" == "1" || "$NO_START" == "true" ]] && NO_START=1 || NO_START=0
[[ "$NO_SMOKE" == "1" || "$NO_SMOKE" == "true" ]] && NO_SMOKE=1 || NO_SMOKE=0
[[ "$FORCE_RESTART" == "1" || "$FORCE_RESTART" == "true" ]] && FORCE_RESTART=1 || FORCE_RESTART=0

have() { command -v "$1" >/dev/null 2>&1; }

SCRIPT_PATH=""
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# Detect if we are running from inside a checkout (not curl|bash /dev/fd)
RUNNING_FROM_TREE=0
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/pyproject.toml" ]]; then
  if grep -q 'oddbeaker-tts' "$SCRIPT_DIR/pyproject.toml" 2>/dev/null; then
    RUNNING_FROM_TREE=1
  fi
fi

BASE_URL="http://${HOST}:${PORT}"
if [[ -z "$CACHE_DIR" ]]; then
  if [[ -n "${XDG_CACHE_HOME:-}" ]]; then
    CACHE_DIR="$XDG_CACHE_HOME/oddbeaker-tts"
  else
    CACHE_DIR="$HOME/.cache/oddbeaker-tts"
  fi
fi
if [[ -z "$DIR" ]]; then
  if [[ -n "${XDG_DATA_HOME:-}" ]]; then
    DIR="$XDG_DATA_HOME/oddbeaker-tts"
  else
    DIR="$HOME/.local/share/oddbeaker-tts"
  fi
fi

PLATFORM="linux"
case "$(uname -s)" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  *) warn "Unsupported OS $(uname -s) — continuing best-effort" ;;
esac

# --- helpers ---

is_tts_tree() {
  local d="$1"
  [[ -d "$d" ]] || return 1
  [[ -f "$d/pyproject.toml" ]] || return 1
  grep -q 'oddbeaker-tts' "$d/pyproject.toml" 2>/dev/null
}

tts_health_ok() {
  local body
  body="$(curl -fsS --max-time 3 "$BASE_URL/health" 2>/dev/null)" || return 1
  printf '%s' "$body" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' 2>/dev/null
}

port_listening() {
  if have ss; then
    ss -ltn 2>/dev/null | grep -qE ":${PORT}[[:space:]]" && return 0
  fi
  if have lsof; then
    lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  if (echo >/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
    return 0
  fi
  return 1
}

managed_unit_active() {
  if [[ "$PLATFORM" == "linux" ]] && have systemctl; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
    systemctl --user is-active --quiet "$UNIT_NAME" 2>/dev/null && return 0
  fi
  if [[ "$PLATFORM" == "macos" ]] && have launchctl; then
    launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1 && return 0
  fi
  return 1
}

unit_working_dir() {
  if [[ "$PLATFORM" == "linux" ]] && have systemctl; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
    systemctl --user show -p WorkingDirectory --value "$UNIT_NAME" 2>/dev/null || true
  fi
}

discover_source() {
  local c
  if [[ -n "$SOURCE" ]]; then
    printf '%s\n' "$SOURCE"
    return 0
  fi
  if [[ "$RUNNING_FROM_TREE" -eq 1 ]]; then
    printf '%s\n' "$SCRIPT_DIR"
    return 0
  fi
  for c in \
    "$DIR" \
    "$HOME/dev/oddbeaker-tts" \
    "$HOME/oddbeaker-tts" \
    "/opt/oddbeaker-tts" \
    "$HOME/src/oddbeaker-tts"
  do
    if is_tts_tree "$c"; then
      (cd "$c" && pwd)
      return 0
    fi
  done
  if have git; then
    if git ls-remote --heads "$DEFAULT_GIT_HTTPS" >/dev/null 2>&1; then
      printf '%s\n' "$DEFAULT_GIT_HTTPS"
      return 0
    fi
    if git ls-remote --heads "$DEFAULT_GIT_SSH" >/dev/null 2>&1; then
      printf '%s\n' "$DEFAULT_GIT_SSH"
      return 0
    fi
    if git ls-remote --heads "$DEFAULT_GIT_SCP" >/dev/null 2>&1; then
      printf '%s\n' "$DEFAULT_GIT_SCP"
      return 0
    fi
  fi
  # Last resort: HTTPS URL even if ls-remote failed (auth/network may work on clone)
  printf '%s\n' "$DEFAULT_GIT_HTTPS"
  return 0
}

ensure_prereqs() {
  step "Checking prerequisites"
  have python3 || die "python3 is required"
  if ! python3 -m venv --help >/dev/null 2>&1; then
    die "python3 venv module missing (Debian/Ubuntu: sudo apt install python3-venv python3-pip)"
  fi
  have curl || die "curl is required"
  have git || die "git is required (to clone or update the repo)"
  # Optional build helpers for torch/kokoro wheels
  local pyver
  pyver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  ok "python3 $pyver"
  ok "platform: $PLATFORM"
  note "target: $HOST:$PORT  voice=$VOICE  dir=$DIR"
}

resolve_install_dir() {
  local src="$1"
  if is_tts_tree "$src"; then
    # Use the existing tree in place (do not copy into DIR unless src is a URL)
    DIR="$(cd "$src" && pwd)"
    ok "using existing checkout: $DIR"
    return 0
  fi

  # Git URL path
  mkdir -p "$(dirname "$DIR")"
  if [[ -d "$DIR/.git" ]] && is_tts_tree "$DIR"; then
    ok "already cloned at $DIR"
    git -C "$DIR" fetch --quiet origin 2>/dev/null || true
    if git -C "$DIR" rev-parse --verify "origin/$REF" >/dev/null 2>&1; then
      git -C "$DIR" checkout --quiet "$REF" 2>/dev/null || true
      git -C "$DIR" pull --ff-only --quiet origin "$REF" 2>/dev/null || true
    elif git -C "$DIR" rev-parse --verify "origin/main" >/dev/null 2>&1; then
      git -C "$DIR" checkout --quiet main 2>/dev/null || true
    elif git -C "$DIR" rev-parse --verify "origin/master" >/dev/null 2>&1; then
      git -C "$DIR" checkout --quiet master 2>/dev/null || true
    fi
    return 0
  fi
  if [[ -e "$DIR" && ! -d "$DIR/.git" ]]; then
    if is_tts_tree "$DIR"; then
      ok "using non-git tree at $DIR"
      return 0
    fi
    die "install path exists but is not oddbeaker-tts: $DIR (set ODDBEAKER_TTS_DIR or --dir)"
  fi
  step "Cloning oddbeaker-tts → $DIR"
  if git clone --quiet --branch "$REF" -- "$src" "$DIR" 2>/dev/null; then
    ok "cloned ($REF)"
    return 0
  fi
  rm -rf "$DIR" 2>/dev/null || true
  if git clone --quiet -- "$src" "$DIR"; then
    ok "cloned (default branch)"
    return 0
  fi
  die "failed to clone from $src"
}

write_config() {
  local cfg="$DIR/etc/tts.json"
  mkdir -p "$DIR/etc"
  if [[ -f "$cfg" ]]; then
    # Update default_voice only if file is valid JSON; keep catalog
    if have python3; then
      python3 - "$cfg" "$VOICE" <<'PY' || true
import json, sys
path, voice = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    sys.exit(0)
if data.get("default_voice") != voice:
    data["default_voice"] = voice
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.write("\n")
PY
    fi
    ok "config: $cfg (default_voice=$VOICE)"
    return 0
  fi
  # Seed from packaged data if present
  local packaged="$DIR/src/oddbeaker_tts/data/tts.json"
  if [[ -f "$packaged" ]]; then
    cp "$packaged" "$cfg"
    python3 - "$cfg" "$VOICE" <<'PY' 2>/dev/null || true
import json, sys
path, voice = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
data["default_voice"] = voice
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)
    f.write("\n")
PY
    ok "wrote config from package defaults: $cfg"
    return 0
  fi
  cat >"$cfg" <<EOF
{
    "engine": "kokoro",
    "default_voice": "$VOICE",
    "cache_enabled": true,
    "cache_max_mb": 200,
    "voices": [
        {"id": "af_heart",     "label": "Heart",    "gender": "female", "accent": "american"},
        {"id": "af_bella",     "label": "Bella",    "gender": "female", "accent": "american"},
        {"id": "am_adam",      "label": "Adam",     "gender": "male",   "accent": "american"},
        {"id": "am_michael",   "label": "Michael",  "gender": "male",   "accent": "american"},
        {"id": "bf_emma",      "label": "Emma",     "gender": "female", "accent": "british"},
        {"id": "bf_isabella",  "label": "Isabella", "gender": "female", "accent": "british"},
        {"id": "bm_george",    "label": "George",   "gender": "male",   "accent": "british"},
        {"id": "bm_daniel",    "label": "Daniel",   "gender": "male",   "accent": "british"}
    ]
}
EOF
  ok "wrote config: $cfg"
}

pip_install_runtime() {
  local venv="$DIR/.venv"
  step "Python venv + runtime dependencies"
  note "This can take several minutes (torch + kokoro + model deps)..."
  if [[ ! -x "$venv/bin/python" ]]; then
    python3 -m venv "$venv" || die "python3 -m venv failed in $DIR"
    ok "created venv $venv"
  else
    ok "reusing venv $venv"
  fi
  "$venv/bin/pip" install --upgrade pip setuptools wheel >/dev/null 2>&1 || true

  local has_gpu=0
  if have nvidia-smi && nvidia-smi >/dev/null 2>&1; then
    has_gpu=1
    ok "NVIDIA GPU detected — using default torch build"
  else
    note "no NVIDIA GPU — preferring CPU torch wheels"
    if ! "$venv/bin/pip" install --quiet torch --index-url https://download.pytorch.org/whl/cpu; then
      warn "CPU torch pre-install failed — continuing with default pip resolver"
    else
      ok "CPU torch installed"
    fi
  fi

  if ! "$venv/bin/pip" install --quiet -e "$DIR[runtime]"; then
    warn "pip install -e '.[runtime]' failed — trying base package"
    "$venv/bin/pip" install --quiet -e "$DIR" \
      || die "pip install oddbeaker-tts failed (check network, build tools, disk space)"
  else
    ok "oddbeaker-tts[runtime] installed"
  fi

  # spaCy model used by Kokoro / phonemizer path
  if "$venv/bin/python" -c "import spacy" >/dev/null 2>&1; then
    if ! "$venv/bin/python" -c "import spacy; spacy.load('en_core_web_sm')" >/dev/null 2>&1; then
      note "downloading spaCy en_core_web_sm..."
      "$venv/bin/python" -m spacy download en_core_web_sm >/dev/null 2>&1 \
        || warn "spaCy model download failed (synthesis may still work)"
    else
      ok "spaCy en_core_web_sm present"
    fi
  else
    # kokoro may pull spacy transitively; try download anyway
    "$venv/bin/python" -m spacy download en_core_web_sm >/dev/null 2>&1 || true
  fi

  [[ -x "$venv/bin/oddbeaker-tts" ]] || die "oddbeaker-tts entrypoint missing after pip install"
  ok "entrypoint: $venv/bin/oddbeaker-tts"
}

prewarm_model() {
  step "Ensuring Kokoro model weights (Hugging Face cache)"
  note "First run may download hundreds of MB from hexgrad/Kokoro-82M..."
  mkdir -p "$CACHE_DIR"
  # Use package helper so HF_HUB_OFFLINE logic matches the service
  if "$DIR/.venv/bin/python" - <<'PY'
import os, sys
sys.path.insert(0, "src")
try:
    from oddbeaker_tts.service import ensure_kokoro_model
    ensure_kokoro_model()
    print("ok")
except Exception as e:
    print(f"fail:{e}", file=sys.stderr)
    sys.exit(1)
PY
  then
    ok "Kokoro model ready in HF cache"
  else
    warn "model pre-download failed — service will retry on first start (needs network)"
  fi
}

write_linux_unit() {
  local venv="$DIR/.venv"
  local unitdir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  local unit="$unitdir/$UNIT_NAME"
  local cfg="$DIR/etc/tts.json"
  mkdir -p "$unitdir" "$CACHE_DIR"

  cat >"$unit" <<EOF
[Unit]
Description=Oddbeaker TTS Service (Kokoro)
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$venv/bin/oddbeaker-tts --host $HOST --port $PORT --config $cfg --cache-dir $CACHE_DIR
Restart=on-failure
RestartSec=5
Environment=HOME=$HOME
Environment=PATH=$venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=LANG=C.UTF-8
Environment=ODDBEAKER_TTS_CONFIG=$cfg
Environment=ODDBEAKER_TTS_CACHE_DIR=$CACHE_DIR
Environment=ODDBEAKER_TTS_HOST=$HOST
Environment=ODDBEAKER_TTS_PORT=$PORT

[Install]
WantedBy=default.target
EOF
  ok "wrote user unit $unit"

  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

  if have loginctl; then
    if loginctl enable-linger "$(id -un)" 2>/dev/null; then
      ok "linger enabled for $(id -un) (survives logout/reboot)"
    else
      # May need root once
      if have sudo && sudo -n loginctl enable-linger "$(id -un)" 2>/dev/null; then
        ok "linger enabled via sudo"
      else
        warn "could not enable linger — run: loginctl enable-linger \$USER"
        note "without linger, the user unit stops on logout"
      fi
    fi
  fi

  if have systemctl && { [[ -n "${XDG_RUNTIME_DIR:-}" ]] || [[ -S "/run/user/$(id -u)/bus" ]]; }; then
    systemctl --user daemon-reload 2>/dev/null || true
    if systemctl --user enable "$UNIT_NAME" 2>/dev/null; then
      ok "enabled $UNIT_NAME"
    else
      warn "systemctl --user enable failed"
    fi
    if systemctl --user restart "$UNIT_NAME" 2>/dev/null || systemctl --user start "$UNIT_NAME" 2>/dev/null; then
      ok "started $UNIT_NAME"
      return 0
    fi
    warn "systemctl --user start failed — trying nohup fallback"
    return 1
  fi
  warn "no user systemd bus — trying nohup fallback"
  return 1
}

write_macos_launchd() {
  local venv="$DIR/.venv"
  local cfg="$DIR/etc/tts.json"
  local plist="$HOME/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"
  local logdir="$HOME/Library/Logs/oddbeaker-tts"
  mkdir -p "$(dirname "$plist")" "$logdir" "$CACHE_DIR"

  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$venv/bin/oddbeaker-tts</string>
    <string>--host</string>
    <string>$HOST</string>
    <string>--port</string>
    <string>$PORT</string>
    <string>--config</string>
    <string>$cfg</string>
    <string>--cache-dir</string>
    <string>$CACHE_DIR</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>$venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>ODDBEAKER_TTS_CONFIG</key>
    <string>$cfg</string>
    <key>ODDBEAKER_TTS_CACHE_DIR</key>
    <string>$CACHE_DIR</string>
    <key>ODDBEAKER_TTS_HOST</key>
    <string>$HOST</string>
    <key>ODDBEAKER_TTS_PORT</key>
    <string>$PORT</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$logdir/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$logdir/stderr.log</string>
</dict>
</plist>
EOF
  ok "wrote LaunchAgent $plist"
  launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null || true
  if launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
    ok "loaded $LAUNCHD_LABEL"
    return 0
  fi
  # Older macOS
  if launchctl load -w "$plist" 2>/dev/null; then
    ok "loaded $LAUNCHD_LABEL (legacy load)"
    return 0
  fi
  warn "launchctl load failed — trying nohup fallback"
  return 1
}

start_daemon_nohup() {
  local venv="$DIR/.venv"
  local cfg="$DIR/etc/tts.json"
  local logdir="${XDG_STATE_HOME:-$HOME/.local/state}/oddbeaker-tts"
  local pidfile="$logdir/oddbeaker-tts.pid"
  local logfile="$logdir/oddbeaker-tts.log"
  mkdir -p "$logdir" "$CACHE_DIR"

  if [[ -f "$pidfile" ]]; then
    local old
    old="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
      ok "already running via nohup (pid $old)"
      return 0
    fi
  fi
  note "starting oddbeaker-tts on $HOST:$PORT (nohup)..."
  nohup "$venv/bin/oddbeaker-tts" \
    --host "$HOST" --port "$PORT" \
    --config "$cfg" \
    --cache-dir "$CACHE_DIR" \
    >>"$logfile" 2>&1 &
  echo $! >"$pidfile"
  ok "started pid $(cat "$pidfile") — log $logfile"
}

wait_health() {
  local i=0
  local max=90
  note "waiting for health at $BASE_URL/health (up to ${max}s; model warm-up can be slow)..."
  while (( i < max )); do
    if tts_health_ok; then
      ok "healthy at $BASE_URL/health"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  warn "not healthy within ${max}s"
  note "check: curl -sS $BASE_URL/health"
  if [[ "$PLATFORM" == "linux" ]]; then
    note "logs: journalctl --user -u $UNIT_NAME -n 50 --no-pager"
  fi
  return 1
}

smoke_test() {
  step "Smoke test: POST /synthesize"
  local tmp
  tmp="$(mktemp)"
  local code
  code="$(curl -sS --max-time 120 -o "$tmp" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d "{\"text\":\"Hello from oddbeaker-tts installer.\",\"voice\":\"$VOICE\",\"speed\":1.0}" \
    "$BASE_URL/synthesize" 2>/dev/null || echo "000")"
  if [[ "$code" != "200" ]]; then
    warn "synthesize HTTP $code — body: $(head -c 200 "$tmp" 2>/dev/null || true)"
    rm -f "$tmp"
    return 1
  fi
  if ! grep -q 'audio_url' "$tmp" 2>/dev/null; then
    warn "synthesize response missing audio_url: $(head -c 200 "$tmp")"
    rm -f "$tmp"
    return 1
  fi
  local url
  url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("audio_url") or "")' "$tmp" 2>/dev/null || true)"
  rm -f "$tmp"
  if [[ -z "$url" || "$url" == "None" ]]; then
    warn "synthesize returned empty audio_url (nothing_to_speak?)"
    return 1
  fi
  # Fetch WAV
  if [[ "$url" == /* ]]; then
    url="$BASE_URL$url"
  fi
  local wav
  wav="$(mktemp --suffix=.wav 2>/dev/null || mktemp)"
  if curl -fsS --max-time 30 -o "$wav" "$url" 2>/dev/null; then
    local sz
    sz="$(wc -c <"$wav" | tr -d ' ')"
    if [[ "$sz" -gt 100 ]]; then
      ok "synthesize ok — WAV ${sz} bytes ($VOICE)"
      rm -f "$wav"
      return 0
    fi
  fi
  rm -f "$wav"
  warn "could not download synthesized WAV from $url"
  return 1
}

print_howto() {
  step "How to start / stop / status"
  if [[ "$PLATFORM" == "linux" ]]; then
    cat <<EOF

  systemctl --user start $UNIT_NAME
  systemctl --user stop $UNIT_NAME
  systemctl --user restart $UNIT_NAME
  systemctl --user status $UNIT_NAME
  journalctl --user -u $UNIT_NAME -f

  # After reboot (with linger): unit starts with your user session.
  # Enable linger if needed:  loginctl enable-linger \$USER

EOF
  elif [[ "$PLATFORM" == "macos" ]]; then
    cat <<EOF

  launchctl kickstart -k gui/\$(id -u)/$LAUNCHD_LABEL
  launchctl bootout gui/\$(id -u)/$LAUNCHD_LABEL
  launchctl print gui/\$(id -u)/$LAUNCHD_LABEL

  Logs: ~/Library/Logs/oddbeaker-tts/

EOF
  fi
  cat <<EOF
  Manual foreground:
    $DIR/.venv/bin/oddbeaker-tts --host $HOST --port $PORT --config $DIR/etc/tts.json

  Health:      curl -sS $BASE_URL/health
  Voices:      curl -sS $BASE_URL/voices
  Synthesize:  curl -sS -H 'Content-Type: application/json' \\
                 -d '{"text":"Hello","voice":"$VOICE"}' \\
                 $BASE_URL/synthesize

  Install dir: $DIR
  Cache dir:   $CACHE_DIR
  Config:      $DIR/etc/tts.json
  Re-run:      $DIR/install.sh   # or curl|bash again

EOF
}

start_service() {
  if [[ "$NO_START" -eq 1 ]]; then
    note "--no-start: not launching daemon"
    return 0
  fi

  if tts_health_ok && [[ "$FORCE_RESTART" -ne 1 ]]; then
    local wd
    wd="$(unit_working_dir)"
    ok "already healthy at $BASE_URL"
    if [[ -n "$wd" && "$wd" != "$DIR" ]]; then
      note "live unit WorkingDirectory=$wd (this install tree is $DIR)"
      note "not restarting foreign/live service (omit --force-restart; safe re-run)"
    elif managed_unit_active; then
      note "managed unit already active — left running"
    else
      note "port $PORT healthy but not our unit — left as-is"
    fi
    # Still refresh unit file on disk for next restart, without bouncing live service
    if [[ "$PLATFORM" == "linux" ]]; then
      local unitdir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
      local unit="$unitdir/$UNIT_NAME"
      # Only rewrite unit if it already points at this DIR, or no unit exists
      if [[ ! -f "$unit" ]] || grep -q "$DIR" "$unit" 2>/dev/null; then
        local venv="$DIR/.venv"
        local cfg="$DIR/etc/tts.json"
        mkdir -p "$unitdir" "$CACHE_DIR"
        cat >"$unit" <<EOF
[Unit]
Description=Oddbeaker TTS Service (Kokoro)
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$venv/bin/oddbeaker-tts --host $HOST --port $PORT --config $cfg --cache-dir $CACHE_DIR
Restart=on-failure
RestartSec=5
Environment=HOME=$HOME
Environment=PATH=$venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=LANG=C.UTF-8
Environment=ODDBEAKER_TTS_CONFIG=$cfg
Environment=ODDBEAKER_TTS_CACHE_DIR=$CACHE_DIR
Environment=ODDBEAKER_TTS_HOST=$HOST
Environment=ODDBEAKER_TTS_PORT=$PORT

[Install]
WantedBy=default.target
EOF
        ok "refreshed unit file (not restarted): $unit"
        systemctl --user daemon-reload 2>/dev/null || true
      else
        note "existing unit file does not match $DIR — left unchanged"
      fi
    fi
    return 0
  fi

  if port_listening && ! tts_health_ok; then
    warn "port $PORT is in use but /health failed — not starting a second daemon"
    note "free the port or set ODDBEAKER_TTS_PORT / --port"
    return 1
  fi

  if tts_health_ok && [[ "$FORCE_RESTART" -eq 1 ]]; then
    note "--force-restart: bouncing managed service"
    if [[ "$PLATFORM" == "linux" ]] && managed_unit_active; then
      local wd
      wd="$(unit_working_dir)"
      if [[ -n "$wd" && "$wd" != "$DIR" ]]; then
        warn "refusing --force-restart: active unit uses $wd, not $DIR"
        return 0
      fi
    fi
  fi

  step "Installing service + starting"
  if [[ "$PLATFORM" == "macos" ]]; then
    write_macos_launchd || start_daemon_nohup || return 1
  else
    write_linux_unit || start_daemon_nohup || return 1
  fi
  wait_health || true
}

# --- main ---

main() {
  printf '\n'
  printf '%s\n' "  oddbeaker-tts installer"
  printf '%s\n' "  ======================"
  printf '\n'

  ensure_prereqs

  step "Locating source"
  local src
  src="$(discover_source)"
  note "source: $src"
  resolve_install_dir "$src"

  write_config
  pip_install_runtime
  prewarm_model
  start_service

  local healthy=0
  if tts_health_ok; then
    healthy=1
  fi

  if [[ "$healthy" -eq 1 && "$NO_SMOKE" -ne 1 && "$NO_START" -ne 1 ]]; then
    smoke_test || warn "smoke test failed — service may still be warming; retry synthesize shortly"
  fi

  print_howto

  if [[ "$healthy" -eq 1 ]]; then
    step "Done"
    ok "oddbeaker-tts is ready at $BASE_URL"
    exit 0
  fi

  if [[ "$NO_START" -eq 1 ]]; then
    step "Done (not started)"
    ok "package installed at $DIR"
    exit 0
  fi

  step "Finished with warnings"
  warn "install completed but $BASE_URL/health is not OK yet"
  note "try: $DIR/.venv/bin/oddbeaker-tts --host $HOST --port $PORT"
  exit 1
}

main "$@"
