---
name: quiz-setups
description: A page for every question type the Quiz school's question creators can make - the 18 professional gold setups (liquidity sweeps, opening-range breakouts, session-average reclaims, fair value gaps, prior-day tests and breaks, Asian-range raids, trend pullbacks, stretch fades), the stay-out spots and the traps - with what the chart shows, why pros take it, the exact trade the quiz checks, when it turns into a trap, what the agent looks at, and what to do when the agent is stuck on it. Use this whenever the user or Hermes asks what a quiz question or setup means, why a setup's answer is buy/sell/stay out, why the agent keeps missing a setup, or how pros trade one of these setups on gold.
---

# Quiz setups: one page per question type

The quiz's question creators make questions of these 20 kinds from real XAUUSD M1 history (`agent/quiz.py`,
`_candidates`). Each page explains one kind. The quiz agent itself is a small neural network and can't read these
pages. They are for Claude and for Hermes (its `setup_guide` tool reads them), so both can explain questions,
judge the agent's answers, and decide what to change when it gets stuck.

| Setup | Answer | What the question shows |
|---|---|---|
| [Liquidity sweep below lows](references/sweep_long.md) | BUY | In the last 5 candles price dipped below the lowest low of the previous hour (60 M1 candles) and closed back above it: a stop run under an obvious low. |
| [Liquidity sweep above highs](references/sweep_short.md) | SELL | In the last 5 candles price poked above the highest high of the previous hour and closed back below it: a stop run over an obvious high. |
| [Opening-range breakout up](references/orb_long.md) | BUY | The first close more than 0. |
| [Opening-range breakout down](references/orb_short.md) | SELL | The first close more than 0. |
| [Reclaimed session average](references/avg_reclaim_long.md) | BUY | The H1 structure is up and price crosses back above the session average (the running average price since the day's open, a stand-in for VWAP). |
| [Lost session average](references/avg_reclaim_short.md) | SELL | The H1 structure is down and price falls back below the session average. |
| [Bullish fair value gap](references/fvg_bull.md) | BUY | A new bullish fair value gap: a candle whose low is above the high of the candle two before, a gap left by a fast push up. |
| [Bearish fair value gap](references/fvg_bear.md) | SELL | A new bearish fair value gap: a candle whose high is below the low of the candle two before. |
| [Testing prior-day low](references/pdl_test.md) | BUY | Price came down to within 0. |
| [Testing prior-day high](references/pdh_test.md) | SELL | Price came up to within 0. |
| [Asian low raided](references/asia_sweep_long.md) | BUY | During London/New York, price pushed more than 0. |
| [Asian high raided](references/asia_sweep_short.md) | SELL | Price pushed more than 0. |
| [H1 uptrend pullback](references/trend_pullback_long.md) | BUY | A strong H1 uptrend (structure +2 or more), price above the 200 EMA, dipped under the 20 EMA and closed back above it with an up candle. |
| [H1 downtrend bounce](references/trend_pullback_short.md) | SELL | A strong H1 downtrend (structure -2 or less), price below the 200 EMA, bounced over the 20 EMA and closed back below it with a down candle. |
| [Held above prior-day high](references/pdh_break.md) | BUY | The first close more than 0. |
| [Held below prior-day low](references/pdl_break.md) | SELL | The first close more than 0. |
| [Fade stretch below average](references/fade_stretch_long.md) | BUY | Price is more than 4 ATR below the session average and just printed a strong up candle (body more than half an ATR). |
| [Fade stretch above average](references/fade_stretch_short.md) | SELL | Price is more than 4 ATR above the session average and just printed a strong down candle. |
| [No setup (stay out)](references/wait.md) | STAY OUT | A quiet spot with no level, sweep or breakout nearby. |
| [Traps (all setups)](references/traps.md) | STAY OUT | Any setup above whose stop was hit within 60 minutes. |

## How to use these pages
- **Explaining a question:** open the setup's page. The trade the quiz checked (entry, stop, 2R target, the clean-win
  rule) is the same for every question of that setup.
- **The agent is stuck on a setup:** check the page's "When it turns into a trap" against the weak-spot report
  (quiz-weak-spots). If the stuck questions match those signs and the chart doesn't show them, add an input (news
  timing, today's range against normal, real spread) rather than training longer.
- **Live trading:** the same setups are flagged live by `agent/pro.py` (`active_setups`); the trap signs are the
  reasons to skip one.

Written by Claude from the question creators' code, 2026-09-24. If a setup's rules change in `agent/quiz.py` or
`agent/pro.py`, update its page.
