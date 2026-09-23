# Trading Bot (MT5 · M1)

A desktop app for trading MetaTrader 5 on **1-minute candles**. It includes a machine-learning trading agent
tuned for a **Ryzen 5 7600 + RTX 4060** PC and **Hermes**, an AI assistant with long-term memory that can
also help with anything else.

## Start it
1. Install **Python 3.11** (64-bit) and **MetaTrader 5**. Open MT5, log in (use a demo account first), and press **Ctrl+E** to enable Algo Trading.
2. Double-click **`Trading Bot.bat`**. The first launch sets everything up; after that it opens straight away.

## In the app
- **Market**: live M1 chart, spread, a trade-size calculator, open positions, and a hold-to-flatten kill switch.
- **Train**: *Fetch data*, then *Train*. The model learns from your M1 history on the GPU and is tested on data it never saw.
- **Agent**: choose Paper → Demo → Real, set confidence and risk, and press *Start*. Every bot trade goes into its own ledger with win rate, P/L and R stats.
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
