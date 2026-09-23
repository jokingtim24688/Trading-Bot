# Trading Stocks on MT5

## Contents
1. What you are actually trading
2. Finding stock symbols
3. Reading the specification
4. Sessions & time zones
5. Sizing a stock trade
6. Costs: spread, commission, swap, dividends
7. Corporate actions & events
8. M1 stock trading specifics
9. Regulatory notes
10. Pre-trade checklist

---

## 1. What you are actually trading
| Type | How it appears | Ownership | Notes |
|---|---|---|---|
| **Share CFD** | `AAPL.US`, `#AAPL`, `AAPL`, `Apple` | No: a contract on price | Leverage (often 1:5 retail EU/UK, higher elsewhere), long & short, overnight swap, dividend adjustments |
| **Exchange stock (real shares)** | `AAPL` on an exchange-connected account (netting) | Yes | Exchange execution, real volume, DOM, usually no leverage, commission per share |
| **Stock index CFD** | `US500`, `NAS100`, `US30`, `GER40` | No | Trade the whole market; tighter spreads than single stocks |
| **Stock futures** | `ES`, `NQ` on futures brokers | No | Expiry & rollover |

Check with the broker which one you have. The account type shows in Navigator, and the symbol path
shows in Symbols (e.g. `Stocks\US\AAPL.US`).

## 2. Finding stock symbols
1. Ctrl+U (Symbols) → search the ticker, or browse `Stocks`/`Shares` folders.
2. Double-click to Show → it appears in Market Watch.
3. Python: `mt5.symbols_get(group="*US*")` or `mt5.symbols_get("*AAPL*")`, then `mt5.symbol_select("AAPL.US", True)`.

## 3. Specification (Market Watch → right-click → Specification)
| Field | Typical share CFD | Why it matters |
|---|---|---|
| Contract size | 1 (1 lot = 1 share) | Some brokers use 100; this changes sizing entirely |
| Digits / tick size | 2 / 0.01 | Price increment |
| Min / step volume | 1 / 1 (or 0.1) | Fractional shares only if step < 1 |
| Margin % | 20% (1:5) | Required margin = price × shares × margin% |
| Stops level | 0–50 points | Min SL/TP distance |
| Swap long/short | Negative both usually | Daily financing cost; triple on one weekday (check field) |
| Sessions | Quotes/Trade times in **server time** | Orders fail outside trade times |
| Commission | Per lot/share or % notional | Often in the account type, not the spec |

## 4. Sessions & time zones
- US stocks: 09:30–16:00 **New York time**. Most MT5 servers run on GMT+2/GMT+3 (EET with DST), so the
  US open appears at **16:30 server time** most of the year. Verify: compare `symbol_info_tick().time`
  with UTC.
- The US/EU DST switch dates differ, so for ~2–3 weeks each spring and autumn the offset shifts by an hour.
- Pre/post-market: rarely offered on CFDs. Where offered, spreads are wide.
- EU stocks (DAX members, etc.): 09:00–17:30 CET. UK: 08:00–16:30 London.
- The first 5–15 M1 bars after the open have the widest spreads and the fastest moves. The last 15 minutes
  bring closing-auction flows.
- Positions held over the weekend or overnight carry **gap risk**. Stops don't protect against gaps; the
  fill is at the next available price.

## 5. Sizing a stock trade
```
risk_$        = equity × risk_%
stop_$/share  = |entry − stop|
shares        = floor(risk_$ / stop_$/share / volume_step) × volume_step
lots          = shares / contract_size
margin needed = entry × shares × margin_%
```
Example: $10,000 equity, 1% risk ($100), AAPL entry 190.00, stop 189.50 → $0.50/share → 200 shares.
Notional $38,000, margin at 20% = $7,600. That is a lot of the account on one line, so also cap notional
exposure (e.g. ≤ 2× equity per position). Use `scripts/position_size.py`, which handles contract size and step.

## 6. Costs
- **Spread**: on M1 it's the biggest cost. Compare the spread with a typical M1 range: `spread / ATR(14, M1)`.
  Aim for < 0.1–0.15 on liquid names (AAPL, MSFT, NVDA, TSLA, AMZN, META).
- **Commission**: e.g. $0.02/share, min $1. Round trip counts twice.
- **Swap**: charged at server rollover for positions held overnight. Irrelevant if flat before the close.
- **Dividends**: on the ex-date, longs are *credited* and shorts are *debited* the dividend (CFDs). Price drops by ≈ dividend at open.

## 7. Corporate actions & events
- **Earnings**: huge gaps. Avoid holding through them; on M1, avoid the first 30 minutes after release.
- **Splits**: brokers adjust positions; history may show a discontinuity, so re-download history after splits.
- **Macro**: CPI, FOMC, NFP move the whole tape. Toolbox → Calendar shows them. Flatten or stand aside around high-impact releases.
- **Halts / LULD bands**: trading can stop mid-session; stops won't fill during a halt.

## 8. M1 stock trading specifics
- Trade the **most liquid** names and indices only; thin stocks on M1 are mostly spread.
- Use **real volume** if the account is exchange-connected (`rates['real_volume']`); CFDs give tick volume only.
- **VWAP** is the main intraday reference for stocks: session-anchored from the 09:30 bar.
- Opening Range: high/low of the first N M1 bars (5, 15, 30) → breakout or fade setups (`m1_trading.md`).
- Relative strength vs the index: compare the stock's M1 return with `US500`/`NAS100` over the same bars.
- Flat by the close unless you deliberately take overnight risk.

## 9. Regulatory notes (check your jurisdiction)
- **US residents**: most MT5 CFD brokers can't serve US clients. US stock trading via MT5 is limited
  to specific brokers. The **Pattern Day Trader** rule (< $25k, max 3 day trades in 5 days) applies to US
  margin accounts at US brokers, not to offshore CFDs.
- **EU/UK (ESMA/FCA)**: retail leverage on single-stock CFDs is capped at 1:5, with negative balance protection.
- Taxes differ between CFD gains and share gains. Point the user to local rules; don't give tax advice.

## 10. Pre-trade checklist (stocks)
- [ ] Symbol visible, spec read (contract size, step, margin, stops level)
- [ ] Market open now (server time vs NY time checked)
- [ ] No earnings/macro release in the next 30 min
- [ ] Spread/ATR acceptable
- [ ] Size from risk %, notional cap respected
- [ ] SL set; plan for exit before close
