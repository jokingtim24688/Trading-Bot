# Trading Fundamentals (everything you need before placing trades)

## Contents
1. Markets & instruments
2. Price, bid/ask, pips, points, lots
3. Leverage & margin
4. Order types & execution
5. Risk management (the part that decides survival)
6. Position sizing formulas
7. Market sessions
8. Analysis methods
9. Building a strategy
10. Backtesting & validation
11. Performance metrics
12. Trading psychology
13. Journaling
14. Common beginner mistakes

---

## 1. Markets & instruments
- **Forex**: currency pairs (EURUSD, GBPUSD, USDJPY). 24/5. Majors have the tightest spreads.
- **Metals**: XAUUSD (gold), XAGUSD (silver). Very active on M1, moved by USD and news.
- **Indices**: US500, NAS100, US30, GER40, UK100. Represent stock baskets.
- **Stocks**: single companies (see `stocks_on_mt5.md`).
- **Commodities**: USOIL/UKOIL, NGAS.
- **Crypto CFDs**: BTCUSD etc. 24/7 at some brokers, wide spreads.

## 2. Price vocabulary
- **Bid** = price you sell at; **Ask** = price you buy at; **Spread** = Ask − Bid.
- Long positions open at Ask and close at Bid; shorts open at Bid and close at Ask.
- **Point** = smallest price increment (`symbol_info().point`). **Pip** = conventionally 10 points on
  5-digit FX (0.0001 EURUSD, 0.01 USDJPY). Gold: many traders call $0.10 a pip, but conventions vary,
  so always talk in points or price to avoid confusion.
- **Lot**: FX 1.00 = 100,000 base units; XAUUSD 1.00 = 100 oz; stocks usually 1 = 1 share. Check the contract size.
- **Tick value**: account-currency P/L for a one-tick move on 1 lot (`trade_tick_value`).

## 3. Leverage & margin
- Leverage 1:100 → margin = notional / 100. Leverage magnifies losses exactly as much as gains.
- **Free margin** = equity − used margin. **Margin level** = equity / used margin × 100%.
- **Margin call** / **stop out** levels (e.g. 100% / 50%): the broker force-closes positions. Size so
  you never get close to them.
- Leverage available ≠ leverage used. Effective leverage = total notional / equity; keep it modest.

## 4. Order types & execution
| Order | Triggers when | Use |
|---|---|---|
| Market buy/sell | Immediately | Enter now; accept slippage |
| Buy limit | Ask ≤ price (below market) | Buy a pullback |
| Sell limit | Bid ≥ price (above market) | Sell a rally |
| Buy stop | Ask ≥ price (above market) | Buy a breakout |
| Sell stop | Bid ≤ price (below market) | Sell a breakdown |
| Stop-limit | Stop triggers, then places a limit | Breakout with price control |
| Stop loss | Attached exit at worse price | Cap loss |
| Take profit | Attached exit at better price | Bank gain |
| Trailing stop | SL follows price by N points | Lock in trend gains |

**Execution modes**: Instant (requotes possible), Market (fill at available price, slippage),
Exchange (real exchange matching). **Slippage** is normal on M1 around news.
**Filling**: FOK (all or nothing), IOC (fill what you can, cancel rest), Return (rest stays as order).

## 5. Risk management
The goal is to stay in the game long enough for an edge to show.
- **Risk per trade**: 0.25–1% of equity. At 1% risk, 10 losses in a row (which happens) = −9.6%.
  At 5% it's −40%.
- **Daily loss limit**: e.g. −3% equity → stop trading for the day. **Weekly** e.g. −6%.
- **Max concurrent risk**: sum of open risk ≤ 2–3%.
- **Correlation**: EURUSD long + GBPUSD long ≈ one bigger USD-short trade. XAUUSD long + USD short is
  also correlated. Count correlated positions as one.
- **Always a stop.** Set it where the trade idea is wrong (structure), then size to fit risk, never the reverse.
- **Reward:risk** and **win rate** go together: breakeven win rate = 1 / (1 + R). At 1:1 you need > 50%
  after costs; at 1:2 you need > 33%.
- **Expectancy** = win% × avg win − loss% × avg loss (net of costs). Must be > 0.
- **Risk of ruin** rises sharply with risk % and falls with edge. Small risk % is the cheapest insurance.
- **Drawdown recovery**: −10% needs +11%, −25% needs +33%, −50% needs +100%.

## 6. Position sizing formulas
```
risk_money  = equity × risk_fraction
ticks       = |entry − stop| / tick_size
loss_per_lot= ticks × tick_value
lots        = risk_money / loss_per_lot   → round DOWN to volume_step, clamp to [volume_min, volume_max]
```
Use `scripts/position_size.py`, which reads these from `symbol_info()` or accepts them as arguments.

## 7. Market sessions (UTC, approximate; shift 1h with DST)
| Session | UTC | Character |
|---|---|---|
| Sydney/Tokyo (Asia) | 22:00–07:00 | Quieter; JPY/AUD active; gold drifts/ranges |
| London | 07:00–16:00 | Volume jumps; EUR/GBP/gold trend starts |
| New York | 12:00–21:00 (stocks 13:30–20:00) | USD news at 12:30/14:00 UTC; stocks open |
| **London–NY overlap** | 12:00–16:00 | Highest liquidity, best for M1 |
| Rollover | ~21:00–22:00 | Spreads explode; avoid on M1 |

## 8. Analysis methods
**Price action / structure**: swing highs/lows, higher highs + higher lows = uptrend, support/resistance,
supply/demand zones, breakouts & retests, liquidity sweeps (stop runs beyond obvious highs/lows).
**Candles**: engulfing, pin bar/rejection, inside bar. On M1 single candles are weak signals, so use them only
with context.
**Indicators**:
- Trend: EMA/SMA, VWAP, Supertrend, ADX (strength)
- Momentum: RSI, Stochastic, MACD
- Volatility: ATR (stop sizing), Bollinger Bands, Keltner
- Volume: tick volume, real volume, OBV, volume profile
Indicators lag and are derived from price. Use one per job (trend / trigger / volatility), not five of the same kind.
**Multi-timeframe context**: even on M1-only execution, you can compute higher-timeframe context
*from M1 data* (e.g. resample M1 → 15-minute trend) without changing the chart timeframe.
**Fundamentals / news**: economic calendar (CPI, NFP, FOMC, GDP, PMIs), central bank speeches, earnings.
**Intermarket**: DXY vs gold/EURUSD, yields vs gold/NAS100, VIX vs indices, oil vs CAD.

## 9. Building a strategy
Write it so a computer could follow it:
1. **Market & time**: which symbols, which hours.
2. **Filter / regime**: trend vs range, volatility band, spread limit, news blackout.
3. **Entry trigger**: exact condition on a *closed* bar.
4. **Stop**: structure- or ATR-based.
5. **Target / exit**: fixed R, trailing, time exit, opposite signal.
6. **Size**: risk % via formula.
7. **Management**: breakeven rule, partials, max trades per day.
If a rule can't be coded, it's discretion. That's allowed, but journal it separately.

## 10. Backtesting & validation
- Data: real ticks where possible (MT5 "Every tick based on real ticks").
- Include **spread, commission, slippage**. On M1 these decide everything.
- **In-sample / out-of-sample split** (e.g. 70/30) and **walk-forward** (roll the window).
- Few parameters and broad plateaus of good results beat sharp optimized peaks (overfitting).
- ≥ 200–300 trades for statistical meaning.
- Then **forward test on demo** for weeks, and only then go live with small size.
- Beware look-ahead bias (using bar 0 / future data), survivorship bias (stocks), and data-snooping.

## 11. Performance metrics
| Metric | Meaning | Rough target |
|---|---|---|
| Net profit after costs | The only profit that counts | > 0 |
| Profit factor | gross win / gross loss | > 1.3 (M1 after costs) |
| Win rate | % winners | Depends on R |
| Avg R per trade | Expectancy in R | > 0.1R |
| Max drawdown | Peak-to-trough equity | < 15–20% |
| Sharpe / Sortino | Return per unit risk | > 1 |
| Recovery factor | Net profit / max DD | > 3 |
| Trades | Sample size | ≥ 200 |

## 12. Trading psychology
- Decide the rules before the session; during it, only execute them.
- No revenge trading after losses. The daily loss limit enforces this mechanically.
- Don't widen stops or remove them. Don't add to losers.
- Size small enough that a single loss is emotionally boring.
- M1 creates many decisions → fatigue. Set session blocks (e.g. 90 min) and breaks.
- Automation removes emotion from execution, but not from *overriding* the bot. Define when you're allowed to intervene.

## 13. Journaling
Log per trade: date/time (server & UTC), symbol, direction, entry/stop/target, size, risk $, R result,
setup name, screenshot, spread at entry, emotional state, rule followed Y/N.
Weekly: expectancy per setup, per session, per weekday → drop what doesn't work.
MT5 History → right-click → Report exports raw data. The repo agent writes a CSV journal automatically.

## 14. Common beginner mistakes
- Trading without a stop, or with lots chosen by feel
- Ignoring spread/commission on M1
- Over-optimizing a backtest
- Trading during rollover or right into news
- Treating demo results as live results (slippage and psychology differ)
- Running an EA with no daily loss limit or kill switch
