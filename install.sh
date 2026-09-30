#!/usr/bin/env bash
# Trading Bot — one-line installer for macOS and Linux.
#
#     curl -fsSL https://raw.githubusercontent.com/jokingtim24688/Trading-Bot/HEAD/install.sh | bash
#
# It checks for git and Python, downloads the app to ~/Trading-Bot and starts it. On a Mac it hands over to
# "Trading Bot.command", which does the Apple-silicon, Homebrew and libomp side and builds the .app. Running it
# again just updates what is already there. Nothing needs sudo; nothing touches your MT5 terminal or its logins.
set -euo pipefail

REPO="${REPO:-https://github.com/jokingtim24688/Trading-Bot.git}"
DIR="${DIR:-$HOME/Trading-Bot}"
LAUNCH=1
[ "${1:-}" = "--no-launch" ] && LAUNCH=0
OK="  [ok]   "; NO="  [--]   "; GO="  [..]   "
say() { printf '%s\n' "$*"; }
head_() { printf '\n\033[36m%s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

head_ "Trading Bot — setup"
say "  Folder: $DIR"

OS="$(uname -s)"
case "$OS" in
  Darwin) say "${OK}macOS $(sw_vers -productVersion 2>/dev/null || echo '?') on $(uname -m)" ;;
  Linux)  say "${OK}Linux $(uname -m)" ;;
  *)      say "${NO}$OS isn't supported. Windows has its own installer (install.ps1)."; exit 1 ;;
esac

# --- git -------------------------------------------------------------------
if have git && git --version >/dev/null 2>&1; then
  say "${OK}git $(git --version | sed 's/git version //')"
else
  if [ "$OS" = "Darwin" ]; then
    say "${NO}git isn't set up yet. macOS will now offer the Command Line Tools — accept, wait for it to finish,"
    say "        then run this command again."
    xcode-select --install 2>/dev/null || true
  else
    say "${NO}git is missing. Install it (apt install git / dnf install git) and run this again."
  fi
  exit 1
fi

# --- Python ----------------------------------------------------------------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  have "$c" || continue
  [ "$(command -v "$c")" = "/usr/bin/python3" ] && [ "$OS" = "Darwin" ] && continue   # Apple's stub
  v="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)"
  case "$v" in 3.1[0-3]) PY="$c"; say "${OK}Python $v ($c)"; break ;; esac
done
if [ -z "$PY" ]; then
  if [ "$OS" = "Darwin" ]; then
    say "${NO}Python 3.10-3.13 not found — \"Trading Bot.command\" installs it for you after the download."
  else
    say "${NO}Python 3.10-3.13 not found. Install it (apt install python3 python3-venv) and run this again."
    exit 1
  fi
fi

# --- the app ---------------------------------------------------------------
if [ -d "$DIR/.git" ]; then
  say "${GO}updating the copy already in $DIR…"
  git -C "$DIR" pull --ff-only || say "${NO}couldn't update (local changes?) — carrying on with what is there."
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  say "${NO}$DIR already exists and isn't empty. Set DIR=... to pick another folder."; exit 1
else
  say "${GO}downloading the app…"
  git clone --depth 50 "$REPO" "$DIR"
fi
chmod +x "$DIR/Trading Bot.command" "$DIR/install.sh" 2>/dev/null || true
say "${OK}app in $DIR"

if [ "$OS" = "Darwin" ]; then
  head_ "Handing over to the Mac installer…"
  say "  It checks your chip, Homebrew, libomp and Python, builds \"Trading Bot.app\" and opens the app."
  [ "$LAUNCH" = "1" ] && exec "$DIR/Trading Bot.command" --from-app
  exit 0
fi

# --- Linux: venv + packages ------------------------------------------------
cd "$DIR"
if [ ! -x ".venv/bin/python" ]; then
  say "${GO}building the Python environment (a few minutes the first time)…"
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
fi
if ! cmp -s requirements.txt .venv/requirements.installed; then
  say "${GO}installing packages…"
  .venv/bin/python -m pip install -r requirements.txt && cp requirements.txt .venv/requirements.installed
fi
say "${OK}ready"
head_ "Done."
say "  Start it any time with:  cd \"$DIR\" && .venv/bin/python -m app.main"
say "  MetaTrader 5 only runs on Windows, so the MT5 side needs the bridge (see MT5 Bridge.bat and the README)."
say "  The Solana side needs nothing but the app."
if [ "$LAUNCH" = "1" ]; then
  head_ "Starting it now…"
  exec .venv/bin/python -m app.main
fi
