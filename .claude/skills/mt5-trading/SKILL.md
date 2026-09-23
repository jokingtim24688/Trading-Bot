---
name: mt5-trading
description: Complete MetaTrader 5 (MT5) operating and trading manual, locked to M1 (1-minute) candles. Covers running the MT5 terminal end to end (install, login, Market Watch, charts, order ticket, one-click trading, Strategy Tester, MQL5 Editor, Python MetaTrader5 API), trading stocks/share CFDs on MT5 (symbols, sessions, contract specs, dividends, gaps), general trading knowledge (risk and position sizing, order types, sessions, spreads, M1 scalping setups, indicators, backtesting, psychology, journaling), and running a local trading agent tuned for an RTX 4060 + Ryzen 5 7600 PC. Use this skill whenever the user mentions MT5, MetaTrader, MQL5, Expert Advisors, forex, gold/XAUUSD, indices, stock CFDs, trading stocks on MT5, scalping, 1-minute charts, lot size, stop loss, backtesting, or the trading bot/agent in this repo, even if they don't name MT5 directly.
---

# MT5 Trading (M1 only)

This skill is a working manual for MetaTrader 5 and for trading in general. Everything
in it assumes the **M1 (1-minute) timeframe**. The user trades M1 only, so every chart,
indicator, backtest, data request, and code sample you produce should use M1 unless the
user explicitly overrides it in that message. In code this means `mt5.TIMEFRAME_M1`
(Python) or `PERIOD_M1` (MQL5). Never leave the timeframe at "current chart" or a default.
M1 was chosen on purpose, so don't talk the user out of it. Do tell them what M1 costs:
more noise, spread is a bigger share of each move, and more trades.

## How to use this skill

Pick the reference that matches the question. Read only what you need, since each file
stands on its own.

| User wants to… | Read |
|---|---|
| Operate the MT5 terminal: install, login, charts, Market Watch, order ticket, hotkeys, settings, Strategy Tester, VPS | `references/mt5_platform.md` |
| Trade stocks / share CFDs on MT5 | `references/stocks_on_mt5.md` |
| Learn or apply general trading: risk, sizing, order types, sessions, strategy, psychology, journaling | `references/trading_fundamentals.md` |
| Design or check an M1 strategy, including spreads, filters, and setups | `references/m1_trading.md` |
| Write an MQL5 EA, indicator, or script | `references/mql5.md` |
| Automate with Python (`MetaTrader5` package), including M1 data and order_send | `references/python_api.md` |
| Run or tune the local trading agent on the RTX 4060 + Ryzen 5 7600 | `references/hardware_agent.md` |
| Gold / XAUUSD specifics | `references/instruments.md` |
| Use the desktop app (chart, agent, training, Hermes assistant) or set up Hermes memory | `references/app_and_hermes.md` |

Scripts in `scripts/` do deterministic work, so run them instead of redoing the math by hand:
- `scripts/position_size.py`: lot size from account risk %, stop distance, and symbol specs.
- `scripts/fetch_m1.py`: pull M1 bars from a running terminal into CSV/Parquet (Windows + MT5).
- `scripts/m1_session_filter.py`: tag M1 bars with trading session (Asia, London, NY, overlap) and flag low-liquidity minutes.

## Core rules when helping

1. **Risk first.** Before any order logic, pin down the risk per trade (default 0.5–1% of
   equity), the stop distance, and the lot size from `position_size.py`. A trade without a
   stop loss is a sizing error, not a strategy.
2. **Demo before live.** New code, new EAs, and new symbols start on a demo account, then go
   through the Strategy Tester on M1 with "Every tick based on real ticks", then a forward
   demo test. Say so when the user is about to go live with something untested.
3. **Check broker specifics.** Symbol names (`XAUUSD`, `XAUUSD.m`, `AAPL.US`, `#AAPL`), contract
   size, tick value, filling mode, stops level, and trading hours all differ by broker. Read
   them with `symbol_info()` or the Specification window rather than assuming.
4. **Be factual, not a tipster.** Explain mechanics, write code, and analyze setups. Don't make
   confident buy/sell calls or promise returns. Add a one-line "not financial advice" when you
   give market analysis.
5. **Handle unknown apps safely.** If the user runs a platform this skill doesn't cover, look up
   its API/automation docs before acting instead of guessing at the UI. Record what you learn
   in `references/learned_apps.md` (create it if missing): app name, control method, and key
   commands.

## M1 quick facts (always relevant)

- One M1 bar = 60 seconds. 1,440 bars per 24h day; a US stock session (09:30–16:00 ET) = 390 bars.
- `copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, n)` pulls M1 bars. Bar 0 is the forming
  bar, so act on bar 1, the last *closed* bar, to avoid repainting.
- MT5 default "Max bars in chart" (Tools → Options → Charts) limits history. Set it to Unlimited or
  a high number before backtesting or fetching long M1 history.
- On M1, spread + commission often equals 20–50% of a typical bar's range. Always compute
  `spread / ATR(14)` before judging a strategy (see `m1_trading.md`).
- The best M1 liquidity is the London/NY overlap (≈ 12:00–16:00 UTC in summer, 13:00–17:00 in winter). The worst is the
  daily rollover (≈ 21:00–22:00 UTC), when spreads widen sharply.

## Typical workflows

**"How do I do X in MT5?"**: Answer from `mt5_platform.md` with the exact menu path and the
hotkey, if there is one.

**"Build me an EA / bot"**: Confirm symbol, risk %, and entry/exit rules. Write it with M1
hard-coded, stops required, a magic number, a spread filter, and a session filter. Include
Strategy Tester settings. Use `mql5.md` or `python_api.md`.

**"Trade stocks on MT5"**: Walk through `stocks_on_mt5.md`: find the symbol, read the spec,
check session hours, size with `position_size.py`, and watch for earnings and dividends.

**"Set up / tune the agent"**: Follow `hardware_agent.md`, which covers the repo's `agent/`
package, hardware settings, and the recommended model stack.

**"Use the app / Hermes"**: The user runs everything from the desktop app (`Trading Bot.bat`), not the
command line. Point them to the tab and button (see `app_and_hermes.md`) rather than CLI commands, unless
they ask for the command.
