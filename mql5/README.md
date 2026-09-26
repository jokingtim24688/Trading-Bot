# MetaTrader 5 programs

| File | What it is |
|---|---|
| `Experts/CandleSense.mq5` | An Expert Advisor. It reads the last closed candles and scores eight signals for buys and sells: H1 trend, liquidity sweep, engulfing, pin bar, breakout, EMA-20 pullback, 3-candle momentum and RSI stretch. It trades the clear winner with an ATR stop and a take profit at 2R. It learns from its own closed trades: a signal that keeps losing gets less weight. |
| `Scripts/SymbolScout.mq5` | Ranks the symbols in your Market Watch by how much room a short-term EA has: candle range vs spread, how cleanly price trends, and daily range. |

## Install (once)
1. In MT5: **File > Open Data Folder**, then open `MQL5`.
2. Copy `Experts/CandleSense.mq5` into `MQL5/Experts/` and `Scripts/SymbolScout.mq5` into `MQL5/Scripts/`.
3. Open MetaEditor (F4), open each file and press **Compile** (F7). It should say "0 errors". If it doesn't, send
   Claude the error lines.
4. Back in MT5, right-click **Expert Advisors / Scripts** in the Navigator and choose **Refresh**.

## Use
1. **Find candidates:**
   - Add the stocks/indices you like to Market Watch, open a chart of each once so their history loads.
   - Drag **SymbolScout** onto any chart. Use `PathFilter` = `Stock` to rank only stocks (if your broker's symbol
     path contains that).
   - The ranking shows on the chart and is saved to `MQL5/Files/SymbolScout.csv`.
2. **Test before trading (the part that matters):**
   - Open the Strategy Tester (Ctrl+R), pick CandleSense and one of the top 3-5 symbols.
   - Use "Every tick based on real ticks" and 6-12 months, then run.
   - Keep a symbol only if the profit factor is over about 1.2, there are 100+ trades and the drawdown is modest.
     Then check the next few months it wasn't tested on (forward test).
3. **Demo first:**
   - Attach CandleSense to that symbol's chart on a **demo** account.
   - Turn on **Algo Trading** (toolbar) and tick "Allow Algo Trading" in the EA's settings.
   - Use one chart per symbol, each with its own `Magic`.

Stocks on MT5 only trade in their exchange's hours (US stocks: 16:30-23:00 on most GMT+3 servers). Set `StartHour` /
`EndHour` to match, and keep `CloseBeforeWeekend` on because of weekend gaps.

Nothing here guarantees profit. The Strategy Tester and a demo account are the only honest judges.
