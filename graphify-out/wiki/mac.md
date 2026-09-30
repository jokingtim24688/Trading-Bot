# Mac (and Linux) support

Added 2026-09-30 by Chat B (commit b7787c0). Windows behaviour is unchanged.

## Install / launch
- **`Trading Bot.command`** (repo root, mode 100755, LF endings via `.gitattributes`): the Mac installer + launcher,
  double-clicked in the Finder (Linux: `bash "Trading Bot.command"`). All logic is inside `main()` so an update that
  rewrites the file mid-run can't garble it. Detects: macOS version (needs 12+), `uname -m` arm64 / x86_64 and Rosetta
  (`sysctl.proc_translated`; re-execs with `arch -arm64`), Homebrew (`/opt/homebrew`, `/usr/local`), Command Line
  Tools (`xcode-select -p`), libomp (`$(brew --prefix)/opt/libomp/lib/libomp.dylib`), Python 3.10-3.13 (skips Apple's
  `/usr/bin/python3` 3.9), then installs what's missing, asking first: CLT (`xcode-select --install`), Homebrew (official
  script), `brew install libomp`, `brew install python@3.12` (or uv's standalone Python without Homebrew). Then `.venv`,
  `python -m app.update`, `pip install -r requirements.txt` only when it changed (`.venv/requirements.installed`),
  an import check (xgboost, lightgbm, sklearn, webview), builds **`Trading Bot.app`** (Info.plist + a script that runs
  the .command with `--from-app`, quarantine removed; git-ignored because it holds this folder's path), launches
  `python -m app.main` with nohup and closes its Terminal window. `--check` only reports, `--no-launch`, `--yes`.
  From the .app: logs to `logs/launcher.log`, first install opens Terminal instead, package updates notify.
- Why libomp: the XGBoost 3.x and LightGBM 4.x macOS wheels link `@rpath/libomp.dylib` from Homebrew and don't include
  it (checked in the wheels). `sol.model.problems()` explains a missing one in the Solana tab and Quiz tab.

## MT5 on a Mac: `agent/mt5_remote.py`
- MetaTrader5's Python package is Windows-only. `RemoteMT5` is a drop-in module object: `__getattr__` turns any
  lowercase name into a call forwarded to the bridge, uppercase names are constants (the bridge's table, `DEFAULTS`
  before it answers). Returns MT5's own result / None / False and keeps `last_error()`. `is_remote = True`.
- Used wherever `import MetaTrader5` fails: `app/mt5_service.py` (its `_ensure` shows the bridge's message),
  `agent/broker.py`, `mcp_server/mt5_mcp.py`. URL + token: `mt5_bridge_url`, `mt5_bridge_token` settings (or env
  `MT5_BRIDGE_URL`/`MT5_BRIDGE_TOKEN`), re-read every 5 s from data/settings.json, so the agent subprocess finds it too.
- Wire format: JSON; named tuples `{__nt__, f, v}` (rebuilt as namedtuples), numpy arrays `{__nd__: base64, descr,
  shape}`, datetimes `{__dt__, off}`, dicts with any keys `{__d__}`, SimpleNamespace `{__ns__}`.
- Windows side: `serve()` (stdlib ThreadingHTTPServer, one lock around MetaTrader5): `GET /ping` (version, constants,
  terminal, account), `POST /call {fn, args, kwargs}`. Token checked with `hmac.compare_digest`; without a token it only
  answers 127.0.0.1 and refuses to listen on the network. `MT5 Bridge.bat` sets up Python, picks a token
  (data/mt5_bridge_token.txt), prints the address + token and serves. The file needs only stdlib + numpy + MetaTrader5.
- App: Settings > MT5 connection (`#set-mt5`: where MT5 runs, address, token, steps, Test button ->
  `POST /api/mt5/bridge/test`). `/api/status` has `platform` (`app/platform_info.py`: os, arch, apple_silicon,
  mac_version, python, mt5_native).

## Window, alerts, helpers
- `app/main.py`: `_Mac` (AppKit via PyObjC, which pywebview's Cocoa backend installs) does what `_Win` does for the
  pop-up: NSStatusWindowLevel, all Spaces + full-screen auxiliary, `orderFrontRegardless` (no focus steal), top right of
  the chosen screen, frontmost-app check for "in front", the TP/SL events feed read from Python; App Nap held off with
  `NSProcessInfo.beginActivityWithOptions`. Popups keep `_native`/`_handle` (either platform). Homebrew dirs added to
  PATH (Finder apps don't get the shell's PATH); menu bar named "Trading Bot"; `_fatal` shows an osascript alert.
- `app/notify.py`: Mac Notification Center via `osascript` (`mac_command`), Linux `notify-send`.
- `app/brain.py`: Ollama found in Homebrew / Ollama.app (`MAC_OLLAMA`), installed with `brew install ollama`
  (`brew_exe`); Hermes Agent runs natively (`bash -lc`), no WSL.
- `app/update.py`: `have_git()` treats Apple's `/usr/bin/git` stub as missing until the Command Line Tools exist.
- UI: `IS_MAC` shows ⌘ / ⌥ in key labels (Cmd already works as Ctrl in `comboOf`), Mac-reserved shortcuts (⌘Q, ⌘H, ⌘M,
  ⌘,), `-webkit-backdrop-filter` everywhere (WKWebView), `applyPlatform()` wording for Settings.
- Tests: `tests/test_platform.py` (bridge round trip against the fake MT5, tokens, encoding, installer on a simulated
  Mac via stub commands, notifications, libomp hint).

## One-line installers (2026-09-30)
`install.ps1` (Windows) and `install.sh` (macOS + Linux), linked at the top of the README:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/jokingtim24688/Trading-Bot/HEAD/install.ps1 | iex"
```
```bash
curl -fsSL https://raw.githubusercontent.com/jokingtim24688/Trading-Bot/HEAD/install.sh | bash
```
Both use `HEAD`, so the link follows whatever the repo's default branch is and never goes stale.

- `install.ps1`: Windows 10/11 check, Python 3.10-3.13 (`py -3.x`, then `python`), git; installs what is missing
  with **winget** after asking (`-Yes` skips the asking), clones to `%USERPROFILE%\Trading-Bot` (or `-Path`),
  makes a Desktop shortcut to `Trading Bot.bat` and starts it. `-Check` only reports, `-NoLaunch` sets up quietly.
  Pure ASCII and no admin rights; `$LASTEXITCODE` is checked instead of piping git's stderr (which turns into a
  terminating error under `$ErrorActionPreference = "Stop"` in PowerShell 5.1).
- `install.sh`: macOS or Linux, git (offers `xcode-select --install` on a Mac), Python 3.10-3.13 skipping Apple's
  `/usr/bin/python3` stub, clones to `~/Trading-Bot` (or `DIR=`). On a Mac it then `exec`s `Trading Bot.command
  --from-app`, which does the chip / Homebrew / libomp / `.app` side. On Linux it builds the venv, installs
  `requirements.txt` only when it changed, and starts `app.main`. `--no-launch` stops before opening the app.
- Running either again updates the copy already there (`git pull --ff-only`) instead of cloning twice.
