# Operating the MT5 Terminal

## Contents
1. Install & login
2. Workspace layout
3. Market Watch & symbols
4. Charts (locked to M1)
5. Placing orders (ticket, one-click, DOM)
6. Managing positions
7. Hotkeys
8. Tools → Options (settings that matter)
9. Indicators, templates, profiles
10. Strategy Tester
11. MQL5 Editor (MetaEditor)
12. Algo Trading / EA permissions
13. Alerts, notifications, journal
14. VPS & uptime
15. Account types: hedging vs netting
16. Troubleshooting

---

## 1. Install & login
- Get the installer from **your broker** (their build is pre-configured with their servers). The generic
  one from metaquotes.net works too; add the server via File → Open an Account → search broker name.
- **File → Login to Trade Account**: login number, password, server (e.g. `Broker-Demo`, `Broker-Live`).
- Trading password = full access. Investor password = read-only (good for monitoring tools).
- Status bar bottom-right: green bars + ping = connected. "No connection" / "Invalid account" = wrong server or password.
- Multiple terminals: install to separate folders (`C:\MT5_Demo`, `C:\MT5_Live`) and launch each with
  `terminal64.exe /portable` so data stays in that folder. The Python API can target one with
  `mt5.initialize(path=r"C:\MT5_Demo\terminal64.exe")`.

## 2. Workspace layout
| Window | Open with | Purpose |
|---|---|---|
| Market Watch | Ctrl+M | Symbol list, bid/ask, spread, Specification |
| Navigator | Ctrl+N | Accounts, indicators, EAs, scripts |
| Toolbox | Ctrl+T | Trade, History, Journal, Experts, Alerts, Calendar |
| Data Window | Ctrl+D | OHLC + indicator values under the cursor |
| Strategy Tester | Ctrl+R | Backtesting & optimization |
| Depth of Market | Alt+B | Level II (exchange symbols / some brokers) |

## 3. Market Watch & symbols
- Right-click → **Symbols** (Ctrl+U) to show hidden symbols (stocks, indices are often hidden by default).
- Right-click → **Specification**: contract size, tick size, tick value, min/max/step volume, stops level,
  swap long/short, trading sessions, margin %, filling modes. Read this before trading any new symbol.
- Right-click → **Columns**: enable Spread, Time, High/Low.
- Symbol suffixes (`.m`, `.raw`, `.pro`, `#`, `.US`) mean different account types or asset classes;
  always use the exact name your account shows.

## 4. Charts (locked to M1)
- New chart: drag symbol from Market Watch or File → New Chart.
- **Timeframe: set M1.** Toolbar "M1" button, or right-click chart → Timeframes → M1, or type `M1` + Enter
  on the chart (quick navigation).
- Chart type: Alt+1 bars, **Alt+2 candles**, Alt+3 line.
- Zoom: + / −. Autoscroll: toolbar button. Chart shift: toolbar button (space on the right).
- **F8** = chart properties (colors, show Ask line, show period separators, show volumes).
- Show Ask line: F8 → Show → Ask price line. Charts are drawn on **Bid**, so without this you won't
  see where buys fill.
- Crosshair: middle mouse or Ctrl+F; drag to measure points/bars between two places.
- Tile all charts: Alt+R. To keep one symbol on several views, use M1 + indicators on separate windows.
- Save the layout as a **Profile** (File → Profiles) so M1 setups reload automatically.

## 5. Placing orders
**Order ticket (F9 / double-click symbol)**
- Type: *Market Execution* (instant) or *Pending Order*.
- Volume in lots; SL / TP in price (click the ▲▼ to step).
- Deviation (instant execution accounts only): max slippage in points.
- Filling policy (FOK / IOC / Return): depends on symbol; shown in Specification.
- Pending types: Buy Limit (below price), Sell Limit (above), Buy Stop (above), Sell Stop (below),
  Buy Stop Limit, Sell Stop Limit. Expiration: GTC, Today, Specified, Specified day.

**One-click trading** (important for M1): Tools → Options → Trade → "One Click Trading" ✓ (accept
the disclaimer). Then Alt+T on a chart shows the Buy/Sell panel. The default volume is set in the panel.

**Trading from the chart**: right-click → Trading → Buy Limit at price, etc. Drag the SL/TP lines of an
open position to modify. Drag the entry line of a pending order to move it.

**Depth of Market (Alt+B)**: click in the ladder to place limit/stop orders at a price level.

## 6. Managing positions
- Toolbox → **Trade** tab lists open positions and orders. Double-click → modify/close. Right-click →
  **Trailing Stop** (runs client-side; the terminal must stay open).
- Partial close: modify → enter a smaller volume → Close.
- Close by (hedging accounts): close one position with an opposite one to save spread.
- Right-click Trade tab → Bulk operations → Close all / close profitable / close losing.
- **History** tab: right-click → custom period; right-click → Report (HTML/XLSX) for journaling.

## 7. Hotkeys
| Key | Action |
|---|---|
| F9 | New order |
| Alt+T | One-click trading panel |
| F8 | Chart properties |
| Ctrl+M / N / T / D / R | Market Watch / Navigator / Toolbox / Data Window / Tester |
| Ctrl+U | Symbols |
| Ctrl+I | Indicator list on chart |
| Ctrl+B | Object list |
| Ctrl+E | Toggle Algo Trading |
| Ctrl+O | Options |
| Ctrl+F | Crosshair |
| F4 | MetaEditor |
| Alt+1/2/3 | Bars/Candles/Line |
| Home / End | Chart start / end |
| Delete / Backspace | Delete selected / last object |
| Ctrl+Y | Period separators |
| Ctrl+G | Grid |
| Ctrl+L | Volumes |

## 8. Tools → Options (Ctrl+O): settings that matter
- **Charts**: Max bars in chart → *Unlimited* (needed for long M1 history). Show trade levels ✓.
- **Trade**: default symbol volume, one-click trading, deviation.
- **Expert Advisors**: Allow algorithmic trading ✓; "Disable algo trading when account/profile/symbol
  changes" (keep ✓ for safety); Allow WebRequest for listed URLs (needed for APIs/news).
- **Notifications**: MetaQuotes ID from the MT5 mobile app → push alerts from EAs (`SendNotification`).
- **Email**: SMTP for `SendMail`.
- **Server**: proxy, "Enable news".

## 9. Indicators, templates, profiles
- Insert → Indicators, or drag from Navigator. Edit: Ctrl+I.
- Useful on M1: EMA 9/21/50, VWAP (custom or built into some builds), ATR(14), RSI(7–14), Bollinger(20,2),
  Volumes (tick volume on CFDs; real volume on exchange symbols).
- Save chart as template: right-click → Templates → Save. Name one `default.tpl` to apply it to every
  new chart. Save one called `M1_scalp.tpl`.
- Profiles save the whole window set (all charts + templates).

## 10. Strategy Tester (Ctrl+R)
- **Settings tab**: Expert, Symbol, **Timeframe = M1**, date range, Forward (e.g. 1/3 out of sample),
  Delays (use "Random delay" or a realistic ms value), **Modelling = "Every tick based on real ticks"**
  (the only honest mode for M1), Deposit, Leverage.
- "1 minute OHLC" mode is fast for rough checks but is misleading on M1 because it can't see intrabar SL/TP order.
- Inputs tab: set parameters; tick "Optimization" to sweep ranges.
- Optimization: *Fast genetic* for large grids; criterion "Custom max" with `OnTester()` return,
  or "Balance + max Sharpe". Always validate on the Forward period.
- Agents tab: use all 12 local threads of the Ryzen 5 7600 (each thread = 1 agent). MQL5 Cloud Network is
  paid and optional.
- Visual mode: watch the EA trade bar by bar for debugging.
- Results: Backtest tab (profit factor, drawdown, Sharpe, recovery factor, trades), Graph, Journal.
- Download history first: View → Symbols → Bars/Ticks tab → request range.

## 11. MQL5 Editor (F4)
- File → New → Expert Advisor / Custom Indicator / Script / Service.
- F7 compile, F5 debug on history or real data. Errors show in the Toolbox → Errors tab.
- Files live in `File → Open Data Folder → MQL5\Experts | Indicators | Scripts | Include | Files`.
- See `mql5.md` for code.

## 12. Algo Trading permissions
Three switches must all be on for an EA to trade:
1. Toolbar **Algo Trading** button green (Ctrl+E).
2. EA properties (F7 on chart) → Common → "Allow Algo Trading" ✓.
3. Tools → Options → Expert Advisors → "Allow algorithmic trading" ✓.
EA status icon in the chart's top-right corner: blue hat = running. Grey/red means disabled.
The Python API also needs Algo Trading enabled to call `order_send`.

## 13. Alerts, notifications, journal
- Toolbox → Alerts → right-click → Create: price/time alerts with sound, email, push.
- **Journal** tab: terminal events (connections, order errors). **Experts** tab: EA `Print()` output.
- Log files: Data Folder → `Logs` and `MQL5\Logs`.

## 14. VPS & uptime
An EA or Python agent only runs while the terminal is open and online. Options:
- Home PC (the 4060 build): disable sleep, set Windows Update active hours, use a UPS.
- MetaQuotes built-in VPS: Navigator → account → right-click → "Register a Virtual Server"; migrate EAs.
  It can't run Python, so Python agents need your own PC or a Windows VPS.
- Low ping to the broker server matters more on M1 than any other timeframe.

## 15. Hedging vs netting
- **Hedging**: many positions per symbol, including opposite ones. Positions are identified by ticket.
- **Netting**: one net position per symbol (common for exchange stocks/futures). Buying against a short reduces it.
Check: `account_info().margin_mode` or the account name in Navigator.

## 16. Troubleshooting
| Symptom / retcode | Meaning / fix |
|---|---|
| 10004 Requote | Price moved; retry with fresh tick or raise deviation |
| 10006 Rejected | Broker rejected; check volume/filling/market hours |
| 10013 Invalid request | Missing field / wrong filling mode |
| 10014 Invalid volume | Not a multiple of `volume_step`, or outside min/max |
| 10015 Invalid price | Stale price; refresh tick |
| 10016 Invalid stops | SL/TP inside `trade_stops_level` or wrong side |
| 10018 Market closed | Outside session (stocks!) |
| 10019 No money | Margin insufficient; reduce lots |
| 10027 AutoTrading disabled by client | Algo Trading button off |
| 10030 Unsupported filling | Use `symbol_info().filling_mode` to pick FOK/IOC/RETURN |
| Chart empty / "waiting for update" | Symbol not in Market Watch, or no history; scroll back / F5 refresh |
| EA not trading | Check the 3 permissions, the Experts tab, and whether the chart is M1 |
