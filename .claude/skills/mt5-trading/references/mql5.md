# MQL5 Reference (M1-locked)

## Program types
| Type | Entry points | Use |
|---|---|---|
| Expert Advisor | `OnInit`, `OnTick`, `OnDeinit`, `OnTimer`, `OnTradeTransaction`, `OnTester` | Automated trading |
| Indicator | `OnInit`, `OnCalculate` | Draw values; no trading |
| Script | `OnStart` | One-shot action |
| Service | `OnStart` (loop) | Background tasks without a chart |

## M1 EA template
Stops required, magic number, spread/session filters, new-bar logic, risk-based sizing, and a daily loss stop.

```mql5
#property strict
#include <Trade/Trade.mqh>
CTrade trade;

input double RiskPercent      = 0.5;    // % equity risked per trade
input double AtrStopMult      = 1.2;    // SL = ATR * mult
input double RewardRisk       = 1.5;    // TP = SL * RR
input int    MaxSpreadPoints  = 30;     // skip if spread above
input int    SessionStartHour = 7;      // server-time hours; adjust to your broker
input int    SessionEndHour   = 20;
input double DailyLossPct     = 3.0;    // stop for the day
input int    MaxTradesPerDay  = 10;
input long   Magic            = 260923;

const ENUM_TIMEFRAMES TF = PERIOD_M1;  // locked
int hFast, hSlow, hTrend, hAtr;
datetime lastBar = 0;
double dayStartEquity = 0; int dayOfYear = -1; int tradesToday = 0;

int OnInit() {
   if(_Period != PERIOD_M1) Print("Chart not M1; EA still uses M1 internally.");
   hFast  = iMA(_Symbol, TF, 20, 0, MODE_EMA, PRICE_CLOSE);
   hSlow  = iMA(_Symbol, TF, 50, 0, MODE_EMA, PRICE_CLOSE);
   hTrend = iMA(_Symbol, TF, 200, 0, MODE_EMA, PRICE_CLOSE);
   hAtr   = iATR(_Symbol, TF, 14);
   if(hFast==INVALID_HANDLE || hSlow==INVALID_HANDLE || hTrend==INVALID_HANDLE || hAtr==INVALID_HANDLE)
      return INIT_FAILED;
   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   IndicatorRelease(hFast); IndicatorRelease(hSlow); IndicatorRelease(hTrend); IndicatorRelease(hAtr);
}

bool NewBar() {
   datetime t = iTime(_Symbol, TF, 0);
   if(t == lastBar) return false;
   lastBar = t; return true;
}

double Buf(int handle, int shift) {
   double v[1];
   if(CopyBuffer(handle, 0, shift, 1, v) != 1) return EMPTY_VALUE;
   return v[0];
}

bool HasPosition() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket) &&
         PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == Magic) return true;
   }
   return false;
}

double LotsForRisk(double stopDist) {
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   double step      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tickSize <= 0 || tickValue <= 0 || stopDist <= 0) return 0;
   double riskMoney = AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0;
   double lossPerLot = stopDist / tickSize * tickValue;
   double lots = MathFloor(riskMoney / lossPerLot / step) * step;
   if(lots < vmin) return 0;           // can't size this small: skip, don't round up risk
   return MathMin(lots, vmax);
}

bool RiskGatesOk() {
   MqlDateTime dt; TimeCurrent(dt);
   if(dt.day_of_year != dayOfYear) {
      dayOfYear = dt.day_of_year; tradesToday = 0;
      dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   }
   if(AccountInfoDouble(ACCOUNT_EQUITY) <= dayStartEquity * (1 - DailyLossPct / 100.0)) return false;
   if(tradesToday >= MaxTradesPerDay) return false;
   if(dt.hour < SessionStartHour || dt.hour >= SessionEndHour) return false;
   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > MaxSpreadPoints) return false;
   return true;
}

void OnTick() {
   if(!NewBar()) return;               // act once per closed M1 bar
   if(HasPosition() || !RiskGatesOk()) return;

   double fast = Buf(hFast, 1), slow = Buf(hSlow, 1), trend = Buf(hTrend, 1), atr = Buf(hAtr, 1);
   if(fast == EMPTY_VALUE || atr == EMPTY_VALUE) return;
   double c1 = iClose(_Symbol, TF, 1), o1 = iOpen(_Symbol, TF, 1), l1 = iLow(_Symbol, TF, 1), h1 = iHigh(_Symbol, TF, 1);

   double stopDist = atr * AtrStopMult;
   double lots = LotsForRisk(stopDist);
   if(lots <= 0) return;

   // Example logic: EMA pullback (setup A in m1_trading.md). Replace with your own rules.
   if(c1 > trend && fast > slow && l1 <= fast && c1 > fast && c1 > o1) {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(trade.Buy(lots, _Symbol, ask, ask - stopDist, ask + stopDist * RewardRisk, "M1 pullback")) tradesToday++;
   }
   else if(c1 < trend && fast < slow && h1 >= fast && c1 < fast && c1 < o1) {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(trade.Sell(lots, _Symbol, bid, bid + stopDist, bid - stopDist * RewardRisk, "M1 pullback")) tradesToday++;
   }
}

double OnTester() {   // custom optimization criterion: profit factor penalized by drawdown
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   double n  = TesterStatistics(STAT_TRADES);
   if(n < 100) return 0;
   return pf * (1.0 - dd / 100.0);
}
```
Normalize prices with `NormalizeDouble(price, _Digits)` if the broker rejects unnormalized SL/TP.
Check `trade.ResultRetcode()` after each call and `Print()` failures.

## Key functions cheat-sheet
| Need | Function |
|---|---|
| Bar data | `iOpen/iHigh/iLow/iClose/iTime/iVolume(_Symbol, PERIOD_M1, shift)`, `CopyRates` |
| Indicator | `iMA, iRSI, iATR, iBands, iMACD, iStochastic, iADX` → `CopyBuffer` |
| Custom indicator | `iCustom(_Symbol, PERIOD_M1, "Name", params...)` |
| Prices | `SymbolInfoDouble(_Symbol, SYMBOL_BID/SYMBOL_ASK)`, `SymbolInfoTick` |
| Symbol spec | `SymbolInfoDouble(..., SYMBOL_VOLUME_MIN/STEP/MAX, SYMBOL_TRADE_TICK_SIZE/VALUE)`, `SYMBOL_TRADE_STOPS_LEVEL` |
| Account | `AccountInfoDouble(ACCOUNT_EQUITY/BALANCE/MARGIN_FREE)` |
| Trading | `CTrade::Buy/Sell/BuyLimit/SellStop/PositionModify/PositionClose` |
| Positions | `PositionsTotal, PositionGetTicket, PositionSelectByTicket, PositionGet*` |
| Orders | `OrdersTotal, OrderGetTicket, OrderGet*` |
| History | `HistorySelect(from,to)`, `HistoryDealsTotal`, `HistoryDealGet*` |
| Time | `TimeCurrent()` (server), `TimeGMT()`, `TimeLocal()` |
| Timer | `EventSetTimer(sec)` → `OnTimer` |
| Files | `FileOpen(..., FILE_CSV|FILE_WRITE)` in `MQL5\Files` |
| HTTP | `WebRequest` (URL must be whitelisted in Options) |
| Alerts | `Alert, Print, SendNotification, SendMail, PlaySound` |
| Chart objects | `ObjectCreate, ObjectSetInteger/Double/String` |

## Indicator template (session VWAP, M1)
```mql5
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots   1
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrDodgerBlue
input int SessionStartHour = 16;   // server hour of cash open (e.g. 16 for 09:30 NY on GMT+3; use minutes below)
input int SessionStartMin  = 30;
double vwap[];
int OnInit(){ SetIndexBuffer(0, vwap, INDICATOR_DATA); return INIT_SUCCEEDED; }
int OnCalculate(const int total, const int prev, const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[]) {
   double pv = 0, vv = 0;
   for(int i = 0; i < total; i++) {
      MqlDateTime t; TimeToStruct(time[i], t);
      if(t.hour == SessionStartHour && t.min == SessionStartMin) { pv = 0; vv = 0; }
      double tp = (high[i] + low[i] + close[i]) / 3.0;
      double v  = (volume[i] > 0 ? (double)volume[i] : (double)tick_volume[i]);
      pv += tp * v; vv += v;
      vwap[i] = vv > 0 ? pv / vv : close[i];
   }
   return total;
}
```
(Recomputes fully each call. Fine for M1 chart lengths; optimize with `prev` if needed.)

## Script: close all positions for this symbol
```mql5
#include <Trade/Trade.mqh>
void OnStart(){
   CTrade t;
   for(int i = PositionsTotal() - 1; i >= 0; i--){
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk) && PositionGetString(POSITION_SYMBOL) == _Symbol) t.PositionClose(tk);
   }
}
```

## Common pitfalls
- Using shift 0 (forming bar) for signals → repainting and fake backtest results.
- Forgetting `SetTypeFillingBySymbol` → 10030 unsupported filling.
- Hard-coding lot sizes → risk drifts as equity changes.
- Not releasing handles in `OnDeinit`, or creating indicator handles inside `OnTick` (slow).
- Server time ≠ your time. Session inputs are in **server time**.
