#!/bin/bash
# Trading Bot for Mac: double-click to install it (the first time) and open it. Later runs update it first.
#
# It works out what it's running on and sets up what that needs:
#   macOS version (12 Monterey or newer), Apple silicon or Intel (a Terminal running under Rosetta is switched to
#   native), Homebrew, Python 3.10-3.13, libomp (XGBoost and LightGBM need it on a Mac), git (Apple's Command Line
#   Tools), the app's own Python environment in .venv, and a "Trading Bot.app" in this folder for daily use.
# It asks before installing anything outside this folder. Your data (data/, logs/, models/) is never touched.
#
# Options: --check (only say what it finds, change nothing), --no-launch (install/update without opening),
#          --yes (don't ask, install what's missing). On Linux run it with: bash "Trading Bot.command"
#
# Everything runs inside main(), which bash reads in full before starting, so an update that rewrites this file can't
# garble the run that's in progress.

main() {
  set -u
  cd "$(dirname "$0")" || exit 1
  ROOT="$(pwd)"
  CHECK=0; LAUNCH=1; YES=0; FROM_APP=0
  for a in "$@"; do
    case "$a" in
      --check) CHECK=1 ;; --no-launch) LAUNCH=0 ;; --yes|-y) YES=1 ;; --from-app) FROM_APP=1 ;;
    esac
  done
  mkdir -p "$ROOT/logs"
  if [ "$FROM_APP" = 1 ]; then exec >>"$ROOT/logs/launcher.log" 2>&1; echo "--- $(date)"; fi

  OS="$(uname -s)"; ARCH="$(uname -m)"; ROSETTA=0; MACOS=""; BREW=""; PY=""
  if [ "$OS" = "Darwin" ]; then
    MACOS="$(sw_vers -productVersion 2>/dev/null)"
    if [ "$ARCH" = "x86_64" ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = "1" ]; then
      ROSETTA=1
      if [ "$CHECK" = 0 ] && arch -arm64 /usr/bin/true 2>/dev/null; then
        say "This Terminal runs under Rosetta; switching to native Apple silicon."
        exec arch -arm64 /bin/bash "$0" "$@"
      fi
    fi
  elif [ "$OS" != "Linux" ]; then
    say "This installer is for macOS (and Linux). On Windows, double-click Trading Bot.bat instead."
    pause_exit 1
  fi

  detect
  report
  [ "$CHECK" = 1 ] && exit 0

  if [ "$OS" = "Darwin" ]; then
    major="${MACOS%%.*}"
    if [ "${major:-0}" -lt 12 ] 2>/dev/null; then
      say "macOS $MACOS is too old: the app's packages need macOS 12 (Monterey) or newer."
      pause_exit 1
    fi
    if [ ! -x "$ROOT/.venv/bin/python" ] && [ "$FROM_APP" = 1 ]; then
      open -a Terminal "$ROOT/Trading Bot.command"          # the first install shows its progress in Terminal
      exit 0
    fi
    need_clt
    need_brew
    need_libomp
  fi
  need_python
  make_venv
  update_and_install
  check_models
  [ "$OS" = "Darwin" ] && make_app
  [ "$LAUNCH" = 1 ] && launch
  exit 0
}

say() { printf '%s\n' "$*"; }

ask() {                                            # ask "question" -> 0 = yes
  [ "$YES" = 1 ] && return 0
  [ "$FROM_APP" = 1 ] && return 1                  # no one to answer: skip optional installs
  printf '%s [Y/n] ' "$1"
  read -r reply </dev/tty || reply="n"
  case "$reply" in [nN]*) return 1 ;; *) return 0 ;; esac
}

pause_exit() {
  if [ "$FROM_APP" = 0 ] && [ -t 0 ]; then printf 'Press Enter to close. '; read -r _ </dev/tty || true; fi
  exit "${1:-1}"
}

py_ok() {                                          # py_ok /path/to/python -> 0 when it's 3.10 to 3.13
  [ -n "$1" ] && [ -x "$1" ] || return 1
  [ "$1" = "/usr/bin/python3" ] && return 1        # Apple's 3.9 (and it pops up an installer without the tools)
  "$1" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)' >/dev/null 2>&1
}

find_python() {
  local c p
  for c in python3.12 python3.11 python3.13 python3.10 \
           /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.12 /usr/local/bin/python3.11 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
           "$HOME/.local/bin/python3.12" python3; do
    p="$(command -v "$c" 2>/dev/null || true)"
    [ -z "$p" ] && [ -x "$c" ] && p="$c"
    if py_ok "$p"; then PY="$p"; return 0; fi
  done
  for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [ -x "$c" ] || continue
    p="$("$c" python find 3.12 2>/dev/null || true)"
    if py_ok "$p"; then PY="$p"; return 0; fi
  done
  PY=""; return 1
}

find_brew() {
  local b
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew "$(command -v brew 2>/dev/null || true)"; do
    if [ -n "$b" ] && [ -x "$b" ]; then BREW="$b"; return 0; fi
  done
  BREW=""; return 1
}

detect() {
  find_brew || true
  find_python || true
  CLT=1
  if [ "$OS" = "Darwin" ]; then xcode-select -p >/dev/null 2>&1 || CLT=0; fi
  LIBOMP=0
  if [ -n "$BREW" ] && [ -e "$("$BREW" --prefix)/opt/libomp/lib/libomp.dylib" ]; then LIBOMP=1; fi
  GIT=0
  if [ "$OS" = "Darwin" ]; then [ "$CLT" = 1 ] && GIT=1; [ -n "$BREW" ] && [ -x "$("$BREW" --prefix)/bin/git" ] && GIT=1
  else command -v git >/dev/null 2>&1 && GIT=1; fi
}

report() {
  if [ "$OS" = "Darwin" ]; then
    local chip="Intel"; [ "$ARCH" = "arm64" ] || [ "$ROSETTA" = 1 ] && chip="Apple silicon"
    say "Detected: macOS $MACOS on $chip ($ARCH$([ "$ROSETTA" = 1 ] && echo ', under Rosetta'))"
    say "  Homebrew:            ${BREW:-not installed}"
    say "  Command Line Tools:  $([ "$CLT" = 1 ] && echo installed || echo 'not installed (git needs them)')"
    say "  libomp:              $([ "$LIBOMP" = 1 ] && echo installed || echo 'not installed (XGBoost and LightGBM need it)')"
  else
    say "Detected: Linux $(uname -r) on $ARCH"
  fi
  say "  Python 3.10-3.13:    ${PY:-not found}"
  say "  git:                 $([ "$GIT" = 1 ] && echo yes || echo no)"
  say "  App environment:     $([ -x "$ROOT/.venv/bin/python" ] && echo "$ROOT/.venv" || echo 'not set up yet')"
  say "  MetaTrader 5:        $( [ "$OS" = "Darwin" ] && echo 'runs on Windows only: connect to it with the MT5 bridge (Settings > MT5 connection)' || echo 'through the MT5 bridge (Settings > MT5 connection)')"
}

need_clt() {
  [ "$CLT" = 1 ] && return 0
  if ask "git (for updates) needs Apple's Command Line Tools. Install them now?"; then
    xcode-select --install >/dev/null 2>&1 || true
    say "A window asks to install the Command Line Tools: click Install and wait for it to finish."
    local i=0
    until xcode-select -p >/dev/null 2>&1; do
      sleep 5; i=$((i + 5))
      if [ "$i" -ge 1800 ]; then say "Still not installed; carrying on without git (no automatic updates)."; return 0; fi
    done
    CLT=1; GIT=1
  fi
}

need_brew() {
  [ -n "$BREW" ] && return 0
  say "Homebrew is the easy way to get Python and libomp (XGBoost and LightGBM need libomp on a Mac)."
  if ask "Install Homebrew now? It asks for your Mac password."; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty || true
    find_brew || say "Homebrew didn't install; carrying on without it."
    [ -n "$BREW" ] && eval "$("$BREW" shellenv)"
  fi
}

need_libomp() {
  [ "$LIBOMP" = 1 ] && return 0
  if [ -n "$BREW" ]; then
    say "Installing libomp (XGBoost and LightGBM need it)..."
    "$BREW" install libomp && LIBOMP=1
  else
    say "Note: without Homebrew there's no libomp, so XGBoost and LightGBM won't load (the app still runs; the Solana"
    say "      crew needs two of its three models, and the MT5 agent's model is XGBoost). Install Homebrew later and"
    say "      run: brew install libomp"
  fi
}

need_python() {
  [ -n "$PY" ] && return 0
  py_ok "$ROOT/.venv/bin/python" && return 0      # the app's own environment already works
  if [ -n "$BREW" ]; then
    say "Installing Python 3.12 with Homebrew..."
    "$BREW" install python@3.12 && PY="$("$BREW" --prefix)/opt/python@3.12/bin/python3.12"
    py_ok "$PY" || find_python || true
  fi
  if [ -z "$PY" ]; then
    say "No Python 3.10-3.13 found. The app can fetch its own copy of Python 3.12 with uv (from astral.sh), inside"
    say "your home folder, no password needed."
    if ask "Get Python 3.12 that way?"; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
      local uv="$HOME/.local/bin/uv"; [ -x "$uv" ] || uv="$HOME/.cargo/bin/uv"
      "$uv" python install 3.12 && PY="$("$uv" python find 3.12 2>/dev/null)"
      py_ok "$PY" || find_python || true
    fi
  fi
  if [ -z "$PY" ]; then
    say "Couldn't find or install Python 3.10-3.13. Install Python 3.12 from https://www.python.org/downloads/macos/"
    say "and double-click Trading Bot.command again."
    pause_exit 1
  fi
}

make_venv() {
  if [ -x "$ROOT/.venv/bin/python" ] && py_ok "$ROOT/.venv/bin/python"; then return 0; fi
  [ -d "$ROOT/.venv" ] && say "The app's Python environment is out of date; making a new one (your data stays)."
  rm -rf "$ROOT/.venv"
  say "First run: setting up the app's Python environment with $("$PY" --version 2>&1). This takes a few minutes..."
  "$PY" -m venv "$ROOT/.venv" || { say "Couldn't create the Python environment."; pause_exit 1; }
  "$ROOT/.venv/bin/python" -m pip install --upgrade pip
}

update_and_install() {
  local py="$ROOT/.venv/bin/python"
  if [ "$GIT" = 1 ] && [ -d "$ROOT/.git" ]; then
    say "Checking for updates..."
    "$py" -m app.update || true
  fi
  if ! cmp -s "$ROOT/requirements.txt" "$ROOT/.venv/requirements.installed"; then
    say "Installing packages..."
    [ "$FROM_APP" = 1 ] && notify "Updating its packages, one moment..."
    if "$py" -m pip install -r "$ROOT/requirements.txt"; then
      cp "$ROOT/requirements.txt" "$ROOT/.venv/requirements.installed"
    else
      say "Installing packages failed (see above). The app may still open with what's installed."
    fi
  fi
}

check_models() {
  local py="$ROOT/.venv/bin/python" bad
  bad="$("$py" -c '
import importlib
bad = []
for m in ("xgboost", "lightgbm", "sklearn", "webview"):
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"{m}: {type(e).__name__}")
print("; ".join(bad))' 2>/dev/null)"
  if [ -n "$bad" ]; then
    say "Some packages didn't load: $bad"
    case "$bad" in *xgboost*|*lightgbm*)
      [ "$OS" = "Darwin" ] && say "  XGBoost/LightGBM on a Mac need libomp: brew install libomp" ;;
    esac
  fi
}

make_app() {
  local app="$ROOT/Trading Bot.app"
  mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
  cat >"$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Trading Bot</string>
  <key>CFBundleDisplayName</key><string>Trading Bot</string>
  <key>CFBundleIdentifier</key><string>local.tradingbot.launcher</string>
  <key>CFBundleExecutable</key><string>TradingBot</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
  cat >"$app/Contents/MacOS/TradingBot" <<LAUNCH
#!/bin/bash
# Made by Trading Bot.command: opens the app from $ROOT without a Terminal window.
exec /bin/bash "$ROOT/Trading Bot.command" --from-app
LAUNCH
  chmod +x "$app/Contents/MacOS/TradingBot"
  xattr -dr com.apple.quarantine "$app" 2>/dev/null || true
  xattr -d com.apple.quarantine "$ROOT/Trading Bot.command" 2>/dev/null || true
}

notify() {
  osascript -e "display notification \"$1\" with title \"Trading Bot\"" >/dev/null 2>&1 || true
}

launch() {
  local py="$ROOT/.venv/bin/python"
  say "Opening Trading Bot..."
  cd "$ROOT" || exit 1
  nohup "$py" -m app.main >>"$ROOT/logs/app.log" 2>&1 </dev/null &
  disown 2>/dev/null || true
  if [ "$OS" = "Darwin" ] && [ "$FROM_APP" = 0 ]; then
    say "From now on you can open it with Trading Bot.app in this folder (drag it to the Dock)."
    # close this Terminal window once the script has ended (the app keeps running)
    (sleep 1; osascript -e 'tell application "Terminal" to close (every window whose name contains "Trading Bot.command")' \
      >/dev/null 2>&1) &
  fi
}

main "$@"; exit $?
