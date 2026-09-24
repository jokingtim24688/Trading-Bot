# Trading Bot (MT5 · M1)

A desktop app for trading MetaTrader 5 on **1-minute candles**. It includes a machine-learning trading agent
tuned for a **Ryzen 5 7600 + RTX 4060** PC and **Hermes**, an AI assistant with long-term memory that can
also help with anything else.

## Start it
1. Install **Python 3.11** (64-bit) and **MetaTrader 5**. Open MT5, log in (use a demo account first), and press **Ctrl+E** to enable Algo Trading.
2. Get the app with git, so it can update itself: install [Git](https://git-scm.com), then in PowerShell
   `git clone -b claude/laughing-bell-3vt2c7 https://github.com/jokingtim24688/Trading-Bot.git`.
   (A ZIP download works but never updates.)
3. Double-click **`Trading Bot.bat`**. The first launch sets everything up. After that it updates itself from GitHub
   on every start, then opens. What the update did is in `logs\update.log` and in the app's Settings.

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
- **Market**: live M1 chart, spread, a trade-size calculator, open positions, and a hold-to-flatten kill switch.
- **Train**: *Fetch data*, then *Train*. The model learns from your M1 history on the GPU and is tested on data it never saw.
- **Agent**: the bot climbs a ladder: Paper (in the app) → Demo → Real · 2 open → Real · 5 open → Real · full. It moves to Demo by itself once it earns enough on Paper; every real-money step needs you to type REAL, and a bad drawdown drops it back a stage. It learns from its own trades and writes those lessons into a skill.
- **Trade alongside it**: bot positions are tagged and drawn on the chart (entry/SL/TP). You get an alert when it enters or exits, and *Size mine* sizes your own copy. Your manual trades are never touched and don't count toward its loss limit.
- **Hermes**: chat with the assistant. It remembers what you tell it (stored on disk) and can check your account,
  summarise the market, size trades, run the agent, take notes, and read web pages.
  Setup: [`hermes/SETUP.md`](hermes/SETUP.md).
- **Settings**: symbols, risk, Hermes connection.

## What's in the repo
| Path | What |
|---|---|
| `app/` | Desktop app (FastAPI backend + UI, pywebview window) |
| `agent/` | M1 agent: features, XGBoost model (GPU training), risk gates, paper/live broker, journal |
| `mcp_server/` | MT5 MCP server so Claude or Hermes Agent can use MT5 (read data, place guarded orders) |
| `hermes/` | Hermes Agent setup, config snippet, memory seed |
| `.claude/skills/mt5-trading/` | Skill: full MT5 manual, stocks on MT5, trading fundamentals, M1 playbook, MQL5, Python API, hardware tuning |
| `.claude/agents/mt5-m1-trader.md` | Claude Code subagent for MT5/M1 work |

## Safety
Paper mode places no orders. Demo mode refuses real-money accounts. Real mode needs an explicit unlock.
Every order carries a stop loss, risk per trade defaults to 0.5%, and trading stops for the day at −3%.
This software is a tool, not financial advice. Test on demo before risking money.
