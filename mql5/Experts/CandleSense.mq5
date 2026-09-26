//+------------------------------------------------------------------+
//| CandleSense.mq5                                                  |
//| A candle-reading Expert Advisor for MetaTrader 5.                |
//|                                                                  |
//| On every closed candle it scores eight things the previous       |
//| candles show, for buys and for sells:                            |
//|   trend (H1 EMA 50/200), liquidity sweep, engulfing, pin bar,    |
//|   breakout with a strong body, EMA-20 pullback, 3-candle          |
//|   momentum, RSI stretch.                                         |
//| It enters when one side's score is high enough and clearly       |
//| ahead of the other, with the stop from ATR (or beyond a sweep's  |
//| wick) and the target at RewardRisk x the stop.                   |
//|                                                                  |
//| It learns from its own trades: every closed trade is filed under |
//| the signal that triggered it, and a signal that keeps losing     |
//| gets less weight (one that keeps winning gets more). The weights |
//| survive restarts (terminal global variables).                    |
//|                                                                  |
//| Protection: risk-% sizing, daily loss stop, max trades a day,    |
//| max open, spread and volatility filters, trading hours,          |
//| break-even and ATR trailing, close before the weekend.           |
//|                                                                  |
//| Test it in the Strategy Tester and on a DEMO account first.      |
//| Nothing here guarantees profit.                                  |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.00"
#property description "Scores the previous candles (trend, sweeps, engulfing, pin bars, breakouts, pullbacks, momentum, RSI), trades the clear winners with ATR stops, and down-weights signals that keep losing."

#include <Trade/Trade.mqh>

//--- inputs
input group "Signals"
input ENUM_TIMEFRAMES SignalTF      = PERIOD_M1;   // Candles it reads
input ENUM_TIMEFRAMES TrendTF       = PERIOD_H1;   // Trend filter timeframe
input int      LookbackBars         = 20;          // Bars for sweeps and breakouts
input double   MinScore             = 4.0;         // Score needed to enter
input double   MinLead              = 2.0;         // ...and this far ahead of the other side
input bool     RequireTrend         = true;        // Only trade with the trend filter
input bool     AdaptiveWeights      = true;        // Learn from its own trades

input group "Exits"
input double   AtrStopMult          = 1.5;         // Stop = ATR x this (sweeps: beyond the wick if wider)
input double   RewardRisk           = 2.0;         // Take profit = stop x this
input double   BreakEvenAtR         = 1.0;         // Move stop to entry after this many R (0 = off)
input double   TrailStartR          = 1.5;         // Start trailing after this many R (0 = off)
input double   TrailAtrMult         = 1.0;         // Trail distance = ATR x this

input group "Risk"
input double   RiskPercent          = 0.5;         // % of equity risked per trade
input int      MaxOpenTrades        = 1;           // Open trades at once (this symbol, this EA)
input int      MaxTradesPerDay      = 10;          // New trades per day
input double   DailyLossPct         = 3.0;         // Stop for the day at this % loss
input int      MaxSpreadPoints      = 0;           // Skip above this spread (0 = auto: 1/4 of ATR)
input double   MinAtrRatio          = 0.6;         // Skip dead markets: ATR below this x its 100-bar average
input double   MaxAtrRatio          = 3.0;         // Skip news spikes: ATR above this x its average

input group "Time (server time)"
input int      StartHour            = 1;           // First hour new trades are allowed
input int      EndHour              = 23;          // New trades stop at this hour
input bool     CloseBeforeWeekend   = true;        // Close everything Friday at FridayCloseHour
input int      FridayCloseHour      = 22;

input group "General"
input long     Magic                = 424242;      // Magic number (unique per chart)
input bool     ShowPanel            = true;        // Scores on the chart

//--- signals
#define NSIG 8
string SigKey[NSIG]  = {"TREND", "SWEEP", "ENGULF", "PINBAR", "BREAKOUT", "PULLBACK", "MOMENTUM", "RSI"};
double SigBase[NSIG] = {1.0,     3.0,     2.0,      2.0,      2.0,        2.0,        1.0,        1.0};
string SigName[NSIG] = {"Trend (H1)", "Liquidity sweep", "Engulfing", "Pin bar", "Breakout", "EMA pullback",
                        "3-candle momentum", "RSI stretch"};

CTrade   trade;
int      hEmaFast, hEmaSlow, hTrendFast, hTrendSlow, hAtr, hRsi;
datetime lastBar = 0;
int      dayKey = -1, tradesToday = 0;
double   dayStartEquity = 0;
string   panel = "";

//+------------------------------------------------------------------+
int OnInit()
  {
   hEmaFast   = iMA(_Symbol, SignalTF, 20, 0, MODE_EMA, PRICE_CLOSE);
   hEmaSlow   = iMA(_Symbol, SignalTF, 50, 0, MODE_EMA, PRICE_CLOSE);
   hTrendFast = iMA(_Symbol, TrendTF, 50, 0, MODE_EMA, PRICE_CLOSE);
   hTrendSlow = iMA(_Symbol, TrendTF, 200, 0, MODE_EMA, PRICE_CLOSE);
   hAtr       = iATR(_Symbol, SignalTF, 14);
   hRsi       = iRSI(_Symbol, SignalTF, 14, PRICE_CLOSE);
   if(hEmaFast == INVALID_HANDLE || hEmaSlow == INVALID_HANDLE || hTrendFast == INVALID_HANDLE ||
      hTrendSlow == INVALID_HANDLE || hAtr == INVALID_HANDLE || hRsi == INVALID_HANDLE)
     {
      Print("CandleSense: couldn't create indicators");
      return INIT_FAILED;
     }
   if(LookbackBars < 3 || RewardRisk <= 0 || AtrStopMult <= 0 || RiskPercent <= 0)
     {
      Print("CandleSense: check the inputs (LookbackBars >= 3, RewardRisk, AtrStopMult and RiskPercent > 0)");
      return INIT_PARAMETERS_INCORRECT;
     }
   trade.SetExpertMagicNumber((ulong)Magic);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(hEmaFast);
   IndicatorRelease(hEmaSlow);
   IndicatorRelease(hTrendFast);
   IndicatorRelease(hTrendSlow);
   IndicatorRelease(hAtr);
   IndicatorRelease(hRsi);
   Comment("");
  }

//--- helpers --------------------------------------------------------
double Buf(const int handle, const int shift)
  {
   double v[1];
   if(CopyBuffer(handle, 0, shift, 1, v) != 1)
      return EMPTY_VALUE;
   return v[0];
  }

double AvgAtr(const int bars)
  {
   double v[];
   int n = CopyBuffer(hAtr, 0, 1, bars, v);
   if(n <= 0)
      return 0;
   double s = 0;
   for(int i = 0; i < n; i++)
      s += v[i];
   return s / n;
  }

int CountOpen()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == Magic)
         n++;
     }
   return n;
  }

double LotsForRisk(const double stopDist)
  {
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0)
      tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tickSize <= 0 || tickValue <= 0 || stopDist <= 0 || step <= 0)
      return 0;
   double riskMoney  = AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0;
   double lossPerLot = stopDist / tickSize * tickValue;
   double lots = MathFloor(riskMoney / lossPerLot / step) * step;
   if(lots < vmin)
      return 0;                                   // can't size that small: skip rather than risk more
   return MathMin(lots, vmax);
  }

//--- adaptive weights (terminal global variables, per symbol + magic) ---
string GvName(const int k, const string what)
  {
   return StringFormat("CS_%s_%I64d_%s_%s", _Symbol, Magic, SigKey[k], what);
  }

double GvGet(const string name)
  {
   return GlobalVariableCheck(name) ? GlobalVariableGet(name) : 0.0;
  }

double Weight(const int k)
  {
   if(!AdaptiveWeights)
      return 1.0;
   double wins = GvGet(GvName(k, "W")), losses = GvGet(GvName(k, "L"));
   double n = wins + losses;
   if(n < 10)
      return 1.0;                                 // too few trades to judge
   double breakEven = 1.0 / (1.0 + RewardRisk);  // win rate that breaks even at this reward:risk
   double w = (wins / n) / breakEven;
   return MathMax(0.25, MathMin(1.75, w));
  }

int SigIndex(const string key)
  {
   for(int k = 0; k < NSIG; k++)
      if(SigKey[k] == key)
         return k;
   return -1;
  }

//--- risk gates -----------------------------------------------------
bool GatesOk(string &why)
  {
   MqlDateTime dt;
   TimeCurrent(dt);
   int key = dt.year * 1000 + dt.day_of_year;
   if(key != dayKey)
     {
      dayKey = key;
      tradesToday = 0;
      dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
     }
   if(AccountInfoDouble(ACCOUNT_EQUITY) <= dayStartEquity * (1.0 - DailyLossPct / 100.0))
     {
      why = "daily loss limit reached";
      return false;
     }
   if(tradesToday >= MaxTradesPerDay)
     {
      why = "max trades today";
      return false;
     }
   if(dt.hour < StartHour || dt.hour >= EndHour)
     {
      why = "outside trading hours";
      return false;
     }
   if(CloseBeforeWeekend && dt.day_of_week == 5 && dt.hour >= FridayCloseHour)
     {
      why = "weekend close";
      return false;
     }
   if(CountOpen() >= MaxOpenTrades)
     {
      why = "max open trades";
      return false;
     }
   return true;
  }

//--- the candle reading ---------------------------------------------
// r[0] = the last CLOSED candle, r[1] the one before, ...
void Score(const MqlRates &r[], const double atr, double &buy[], double &sell[])
  {
   ArrayInitialize(buy, 0);
   ArrayInitialize(sell, 0);
   int n = LookbackBars;

   // 0 trend: H1 EMA 50 vs 200 and price vs EMA 50
   double tf = Buf(hTrendFast, 1), ts = Buf(hTrendSlow, 1);
   if(tf != EMPTY_VALUE && ts != EMPTY_VALUE)
     {
      if(tf > ts && r[0].close > tf)
         buy[0] = 1;
      if(tf < ts && r[0].close < tf)
         sell[0] = 1;
     }

   // range of the candles before the last one
   double hi = r[1].high, lo = r[1].low;
   for(int i = 2; i <= n; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   double body = MathAbs(r[0].close - r[0].open), range = r[0].high - r[0].low;
   double upWick = r[0].high - MathMax(r[0].open, r[0].close);
   double dnWick = MathMin(r[0].open, r[0].close) - r[0].low;

   // 1 liquidity sweep: took the stops beyond the range, closed back inside
   if(r[0].low < lo && r[0].close > lo)
      buy[1] = 1;
   if(r[0].high > hi && r[0].close < hi)
      sell[1] = 1;

   // 2 engulfing
   bool prevBear = r[1].close < r[1].open, prevBull = r[1].close > r[1].open;
   if(prevBear && r[0].close > r[0].open && r[0].close >= r[1].open && r[0].open <= r[1].close)
      buy[2] = 1;
   if(prevBull && r[0].close < r[0].open && r[0].close <= r[1].open && r[0].open >= r[1].close)
      sell[2] = 1;

   // 3 pin bar: long rejection wick, close in the far third
   if(range > 0.5 * atr)
     {
      if(dnWick >= 2.0 * body && dnWick >= 0.6 * range && r[0].close >= r[0].low + 0.66 * range)
         buy[3] = 1;
      if(upWick >= 2.0 * body && upWick >= 0.6 * range && r[0].close <= r[0].low + 0.34 * range)
         sell[3] = 1;
     }

   // 4 breakout: close beyond the range with a strong body
   if(body >= 0.6 * atr)
     {
      if(r[0].close > hi && r[0].close > r[0].open)
         buy[4] = 1;
      if(r[0].close < lo && r[0].close < r[0].open)
         sell[4] = 1;
     }

   // 5 EMA-20 pullback in an EMA 20/50 trend
   double ef = Buf(hEmaFast, 1), es = Buf(hEmaSlow, 1);
   if(ef != EMPTY_VALUE && es != EMPTY_VALUE)
     {
      if(ef > es && r[0].low <= ef && r[0].close > ef && r[0].close > r[0].open)
         buy[5] = 1;
      if(ef < es && r[0].high >= ef && r[0].close < ef && r[0].close < r[0].open)
         sell[5] = 1;
     }

   // 6 three rising / falling candles
   if(r[0].close > r[0].open && r[1].close > r[1].open && r[2].close > r[2].open &&
      r[0].close > r[1].close && r[1].close > r[2].close)
      buy[6] = 1;
   if(r[0].close < r[0].open && r[1].close < r[1].open && r[2].close < r[2].open &&
      r[0].close < r[1].close && r[1].close < r[2].close)
      sell[6] = 1;

   // 7 RSI stretch: oversold helps buys, overbought helps sells (and stretched the other way counts against)
   double rsi = Buf(hRsi, 1);
   if(rsi != EMPTY_VALUE)
     {
      if(rsi < 30)
         buy[7] = 1;
      if(rsi > 70)
         sell[7] = 1;
      if(rsi > 80)
         buy[7] = -1;
      if(rsi < 20)
         sell[7] = -1;
     }
  }

double Total(const double &hit[], int &best)
  {
   double s = 0, top = 0;
   best = -1;
   for(int k = 0; k < NSIG; k++)
     {
      double v = hit[k] * SigBase[k] * Weight(k);
      s += v;
      if(k > 0 && v > top)                        // trend alone never names the trade
        {
         top = v;
         best = k;
        }
     }
   return s;
  }

string Hits(const double &hit[])
  {
   string s = "";
   for(int k = 0; k < NSIG; k++)
      if(hit[k] > 0)
         s += (s == "" ? "" : ", ") + SigName[k];
   return s == "" ? "-" : s;
  }

//--- trade management on every tick --------------------------------
void Manage(const double atr)
  {
   MqlDateTime dt;
   TimeCurrent(dt);
   bool weekend = CloseBeforeWeekend && dt.day_of_week == 5 && dt.hour >= FridayCloseHour;
   double stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != Magic)
         continue;
      if(weekend)
        {
         trade.PositionClose(tk);
         continue;
        }
      if(atr <= 0)
         continue;
      bool isBuy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double open = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      double px = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double risk = MathAbs(open - sl);
      if(risk <= 0)
         risk = atr * AtrStopMult;
      double gainR = (isBuy ? px - open : open - px) / risk;
      double newSl = sl;
      if(BreakEvenAtR > 0 && gainR >= BreakEvenAtR)
        {
         double be = isBuy ? open + 2 * _Point : open - 2 * _Point;
         if(isBuy ? be > newSl : (newSl == 0 || be < newSl))
            newSl = be;
        }
      if(TrailStartR > 0 && gainR >= TrailStartR)
        {
         double tr = isBuy ? px - TrailAtrMult * atr : px + TrailAtrMult * atr;
         if(isBuy ? tr > newSl : (newSl == 0 || tr < newSl))
            newSl = tr;
        }
      newSl = NormalizeDouble(newSl, _Digits);
      if(newSl != sl && MathAbs(px - newSl) > stopsLevel)
         trade.PositionModify(tk, newSl, tp);
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   double atrNow = Buf(hAtr, 1);
   Manage(atrNow == EMPTY_VALUE ? 0 : atrNow);

   datetime t = iTime(_Symbol, SignalTF, 0);
   if(t == lastBar)
      return;                                     // decide once per closed candle
   lastBar = t;

   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, SignalTF, 1, LookbackBars + 3, r) < LookbackBars + 3 || atrNow == EMPTY_VALUE || atrNow <= 0)
      return;

   double buy[NSIG], sell[NSIG];
   Score(r, atrNow, buy, sell);
   int bestB, bestS;
   double sb = Total(buy, bestB), ss = Total(sell, bestS);

   string why = "";
   string decision = "waiting";
   double avg = AvgAtr(100);
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   long maxSpread = MaxSpreadPoints > 0 ? MaxSpreadPoints : (long)(0.25 * atrNow / _Point);

   bool wantBuy  = sb >= MinScore && sb - ss >= MinLead && (!RequireTrend || buy[0] > 0) && bestB >= 0;
   bool wantSell = ss >= MinScore && ss - sb >= MinLead && (!RequireTrend || sell[0] > 0) && bestS >= 0;

   if(!wantBuy && !wantSell)
      why = "no side scored high enough";
   else if(!GatesOk(why))
      decision = "skipped";
   else if(spread > maxSpread)
     {
      why = StringFormat("spread %d > %d points", (int)spread, (int)maxSpread);
      decision = "skipped";
     }
   else if(avg > 0 && (atrNow < MinAtrRatio * avg || atrNow > MaxAtrRatio * avg))
     {
      why = atrNow < MinAtrRatio * avg ? "market too quiet" : "volatility spike (news?)";
      decision = "skipped";
     }
   else
     {
      bool isBuy = wantBuy;
      int best = isBuy ? bestB : bestS;
      double stopDist = atrNow * AtrStopMult;
      if(best == 1)                               // sweep: stop beyond the wick if that's wider (max 3 ATR)
        {
         double wick = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) - r[0].low : r[0].high - SymbolInfoDouble(_Symbol, SYMBOL_BID);
         stopDist = MathMin(3 * atrNow, MathMax(stopDist, wick + 0.2 * atrNow));
        }
      double lots = LotsForRisk(stopDist);
      if(lots <= 0)
        {
         why = "risk too small for the minimum lot";
         decision = "skipped";
        }
      else
        {
         string cmt = "CS:" + SigKey[best];
         bool ok;
         if(isBuy)
           {
            double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
            ok = trade.Buy(lots, _Symbol, ask, NormalizeDouble(ask - stopDist, _Digits),
                           NormalizeDouble(ask + stopDist * RewardRisk, _Digits), cmt);
           }
         else
           {
            double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            ok = trade.Sell(lots, _Symbol, bid, NormalizeDouble(bid + stopDist, _Digits),
                            NormalizeDouble(bid - stopDist * RewardRisk, _Digits), cmt);
           }
         if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_PLACED))
           {
            tradesToday++;
            decision = isBuy ? "BUY" : "SELL";
            why = SigName[best];
           }
         else
           {
            decision = "order failed";
            why = StringFormat("%u %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
           }
         PrintFormat("CandleSense %s %s: buy %.1f / sell %.1f, %s", decision, _Symbol, sb, ss, why);
        }
     }

   if(ShowPanel)
     {
      string w = "";
      for(int k = 0; k < NSIG; k++)
         w += StringFormat("%s %.2f  ", SigKey[k], Weight(k));
      panel = StringFormat("CandleSense  %s %s\nBuy score %.1f: %s\nSell score %.1f: %s\nNeeds %.1f and a %.1f lead%s\n"
                           "Last: %s%s\nTrades today %d/%d, open %d/%d\nWeights: %s",
                           _Symbol, EnumToString(SignalTF), sb, Hits(buy), ss, Hits(sell), MinScore, MinLead,
                           RequireTrend ? ", with the H1 trend" : "", decision, why == "" ? "" : " (" + why + ")",
                           tradesToday, MaxTradesPerDay, CountOpen(), MaxOpenTrades, w);
      Comment(panel);
     }
  }

//--- learning: file each closed trade under the signal that opened it ---
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || !AdaptiveWeights)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != Magic)
      return;
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
      return;
   double pnl = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) + HistoryDealGetDouble(trans.deal, DEAL_SWAP) +
                HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   long posId = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   if(!HistorySelectByPosition(posId))
      return;
   string key = "";
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d > 0 && HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN)
        {
         string c = HistoryDealGetString(d, DEAL_COMMENT);
         if(StringFind(c, "CS:") == 0)
            key = StringSubstr(c, 3);
         break;
        }
     }
   int k = SigIndex(key);
   if(k < 0)
      return;
   string name = GvName(k, pnl > 0 ? "W" : "L");
   GlobalVariableSet(name, GvGet(name) + 1);
   PrintFormat("CandleSense learned: %s trade %s %.2f -> weight now %.2f", SigName[k], pnl > 0 ? "won" : "lost", pnl, Weight(k));
  }

//--- Strategy Tester: optimise for profit factor, penalised by drawdown ---
double OnTester()
  {
   double trades = TesterStatistics(STAT_TRADES);
   if(trades < 50)
      return 0;
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   return pf * (1.0 - dd / 100.0);
  }
//+------------------------------------------------------------------+
