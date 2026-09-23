# mt5-trading skill + subagent
`.claude/skills/mt5-trading/SKILL.md` routes to references:
mt5_platform (terminal A–Z, hotkeys, Strategy Tester, retcodes) · stocks_on_mt5 · trading_fundamentals · m1_trading (cost ratio, filters, setups A–E) · mql5 (M1 EA template, VWAP indicator) · python_api · instruments · hardware_agent · app_and_hermes.
Scripts: position_size.py, fetch_m1.py, m1_session_filter.py. Packaged as `mt5-trading.skill`.
Subagent `.claude/agents/mt5-m1-trader.md`: tools include `mcp__mt5__*`; rules cover risk first, confirmation on real accounts, closed bars only, and the testing ladder.
