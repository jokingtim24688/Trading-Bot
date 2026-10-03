# Trading Bot (MT5 · M1)

A desktop app for trading MetaTrader 5 on **1-minute candles**. It includes a machine-learning trading agent
tuned for a **Ryzen 5 7600 + RTX 4060** PC, a Sim that lets it trade real past markets as if live, and phone alerts and
commands through Telegram.

## Install it in one line
Paste this into **PowerShell** (Windows):
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/jokingtim24688/Trading-Bot/HEAD/install.ps1 | iex"
```
or into **Terminal** (macOS and Linux):
```bash
curl -fsSL https://raw.githubusercontent.com/jokingtim24688/Trading-Bot/HEAD/install.sh | bash
```
Either one checks what your computer already has (Python, git, and on a Mac the chip, Homebrew and `libomp`),
installs only what is missing — asking first — downloads the app to your user folder, and opens it. Run the same
line again later and it just updates. Nothing needs administrator rights, and neither one touches MetaTrader 5 or
its logins. To look before you leap: add `-Check` on Windows, or download the `.sh` and run it with `--no-launch`.
MetaTrader 5 still has to be installed and logged in (Windows only — on a Mac see [On a Mac](#on-a-mac)).

## Start it by hand
**On a Mac?** See [On a Mac](#on-a-mac) below. On Windows:

1. Install **Python 3.11** (64-bit) and **MetaTrader 5**. Open MT5, log in (use a demo account first), and press **Ctrl+E** to enable Algo Trading.
2. Get the app with git, so it can update itself: install [Git](https://git-scm.com), then in PowerShell
   `git clone -b claude/laughing-bell-3vt2c7 https://github.com/jokingtim24688/Trading-Bot.git`.
   (A ZIP download works but never updates.)
3. Double-click **`Trading Bot.bat`**. The first launch sets everything up. After that it updates itself from GitHub
   on every start, then opens. What the update did is in `logs\update.log` and in the app's Settings.

### On a Mac
1. Get the app with git: open **Terminal** and run
   `git clone -b claude/laughing-bell-3vt2c7 https://github.com/jokingtim24688/Trading-Bot.git`
   (if the Mac asks to install the Command Line Tools, click Install, then run the line again).
2. In the Finder, open the **Trading-Bot** folder and double-click **`Trading Bot.command`**. It checks your Mac and
   sets up what's missing, asking first: macOS 12 or newer, Apple silicon or Intel, Homebrew, Python 3.12, `libomp`
   (XGBoost needs it on a Mac) and git. Then it opens the app and makes **`Trading Bot.app`** in the same
   folder: use that from now on (drag it to the Dock). `bash "Trading Bot.command" --check` only says what it finds.
3. If the Mac says the file can't be opened because it's from an unidentified developer: right-click it → **Open**.

Everything runs on the Mac: charts, the Sim, the quiz, Telegram. **MetaTrader 5 itself is the one
exception**: its Python connection only exists on Windows. Run MT5 on a Windows PC or in a Windows VM (Parallels,
VMware Fusion, UTM), double-click **`MT5 Bridge.bat`** there (it shows an address and a token), and enter both in the
app under **Settings → MT5 connection**. The app, the trading agent and the MCP bridge then use that MT5.

### Stuck on an old version?
Open PowerShell in the Trading-Bot folder (right-click the desktop shortcut → *Open file location*, then type
`powershell` in the address bar) and run these once:
```
git fetch origin
git checkout -B claude/laughing-bell-3vt2c7 origin/claude/laughing-bell-3vt2c7
```
If it says *not a git repository*, the folder came from a ZIP: clone it again (step 2) and copy your old `data`
folder into the new one. After this one-time fix, `Trading Bot.bat` keeps it up to date by itself.

## In the app
- **Bot**: three views. **Live**: the M1 chart, what the bot is doing, co-pilot / full auto, Replay and **Sim** (real
  history the model never trained on, played forward like a live market; the bot trades it as if it were running, with
  pretend money and its own record). **Agent details**: stages, backtest, journal. **Hub**: the bot and its checkers as
  cats (they type while it works and celebrate profits), the market, balance, gain, loss, subtotal, the chart and recent trades.
- **Manual**: trade by hand, with a trade-size calculator, open positions, and a hold-to-flatten kill switch.
- **Train**: *Fetch data*, then *Train*. The model learns from your M1 history on the GPU and is tested on data it never saw.
- **Agent**: the bot climbs a ladder: Paper (in the app) → Demo → Real · 2 open → Real · 5 open → Real · full. It moves to Demo by itself once it earns enough on Paper; every real-money step needs you to type REAL, and a bad drawdown drops it back a stage. It learns from its own trades and writes those lessons into a skill.
- **Trade alongside it**: bot positions are tagged and drawn on the chart (entry/SL/TP). You get an alert when it enters or exits, and *Size mine* sizes your own copy. Your manual trades are never touched and don't count toward its loss limit.
- **Settings**: symbols, risk, Keybinds, Sounds, and Phone alerts: Telegram alerts (one summary card when more than 3
  trades close together) and a command maker: say "make /pnl show my total and add it as a button" and it builds it.

## What's in the repo
| Path | What |
|---|---|
| `app/` | Desktop app (FastAPI backend + UI, pywebview window) |
| `agent/` | M1 agent: features, XGBoost model (GPU training), risk gates, paper/live broker, journal |
| `mcp_server/` | MT5 MCP server so Claude can use MT5 (read data, place guarded orders) |
| `.claude/skills/mt5-trading/` | Skill: full MT5 manual, stocks on MT5, trading fundamentals, M1 playbook, MQL5, Python API, hardware tuning |
| `.claude/agents/mt5-m1-trader.md` | Claude Code subagent for MT5/M1 work |

## Safety
Paper mode places no orders. Demo mode refuses real-money accounts. Real mode needs an explicit unlock.
Every order carries a stop loss, risk per trade defaults to 0.5%, and trading stops for the day at −3%.
This software is a tool, not financial advice. Test on demo before risking money.
