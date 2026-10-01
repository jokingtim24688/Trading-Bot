//+------------------------------------------------------------------+
//| CandleSenseSwing.mq5                                             |
//| A simple trend-direction "stacking" EA: no FVG/order-block        |
//| scoring like CandleSenseICT.mq5 - just trades with the chart's    |
//| current direction, repeatedly, up to a high number of concurrent  |
//| trades, each with a small fixed stop and target in points.        |
//|                                                                    |
//| On every new bar, if price is trending (EMA slope / price vs      |
//| EMA), and the price has moved at least MinStackPoints since the   |
//| last entry in that direction, it opens another market order with  |
//| a fixed SL (points) and TP (points) - stacking trades the same    |
//| way a grid/swing scalper does, instead of waiting for one high-   |
//| quality setup like CandleSenseICT.mq5 does.                       |
//|                                                                    |
//| Because many trades can be open at once, per-trade risk is kept   |
//| small on purpose: MaxTotalRiskPct caps what ALL open trades could |
//| lose together if every stop was hit at the same time, and the     |
//| per-trade lot size is worked out from that cap divided by         |
//| MaxOpenTrades - not from a flat risk % per trade, which would let |
//| worst-case loss grow without limit as more trades stack up.       |
//|                                                                    |
//| Test it in the Strategy Tester and on a DEMO account first.       |
//| Nothing here guarantees profit - 60 trades at once with a tight   |
//| 150/200-point stop/target is a high-frequency, high-turnover      |
//| style; it will rack up spread and commission costs fast.          |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.00"
#property description "Trend-direction stacking EA: fixed SL/TP in points, up to N concurrent trades, risk-capped sizing."
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//================================= Inputs ==================================
input group "=== Trend direction ==="
input ENUM_TIMEFRAMES EntryTF        = PERIOD_M5;   // Timeframe checked for a new entry each bar
input int    TrendEMA                = 50;          // EMA period that defines the trend
input int    TrendConfirmBars        = 3;           // EMA must have sloped this many bars in a row

input group "=== Stacking ==="
input double SL_Points               = 150;         // Fixed stop loss, points
input double TP_Points               = 200;         // Fixed take profit, points
input double MinStackPoints          = 60;          // Price must move this far since the last entry before stacking another
input int    MaxOpenTrades           = 60;          // Max concurrent trades (this EA's own magic number only)

input group "=== Sizing & risk ==="
input double MaxTotalRiskPct         = 8.0;         // Worst case: if ALL open trades hit SL together, cap the loss at this % of balance
input double MaxSpreadPoints         = 40;          // Refuse entries when spread exceeds this
input double DailyLossLimitPct       = 10.0;        // Stop trading for the day after this % balance loss
input int    MagicNumber             = 260931;      // Order magic number

input group "=== HUD ==="
input bool   ShowHUD                 = true;        // Show the on-chart Trades/Earned/Lost/Subtotal panel

//================================= State ====================================
double   g_dayStartEquity = 0;
datetime g_dayStamp        = 0;
double   g_lastEntryPrice  = 0;
int      g_lastEntryDir    = 0;   // 1 buy, -1 sell, 0 none yet

int g_hEMA = INVALID_HANDLE;

int    g_hudTrades = 0;
double g_hudEarned = 0, g_hudLost = 0;
#define HUD_PREFIX "CSSWING_HUD_"

// Forward declaration: defined later (Helpers section), used by HUD_Update above it.
int CountMyOpenTrades();

//================================= HUD panel ===================================
void HUD_Label(string name, int x, int y, string text, color clr)
  {
   string full = HUD_PREFIX + name;
   if(ObjectFind(0, full) < 0)
     {
      ObjectCreate(0, full, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, full, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, full, OBJPROP_XDISTANCE, x);
      ObjectSetInteger(0, full, OBJPROP_YDISTANCE, y);
      ObjectSetInteger(0, full, OBJPROP_FONTSIZE, 10);
      ObjectSetString(0, full, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, full, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, full, OBJPROP_HIDDEN, true);
     }
   ObjectSetString(0, full, OBJPROP_TEXT, text);
   ObjectSetInteger(0, full, OBJPROP_COLOR, clr);
  }

void HUD_Create()
  {
   if(!ShowHUD) return;
   ObjectCreate(0, HUD_PREFIX+"bg", OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_XDISTANCE, 8);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_YDISTANCE, 18);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_XSIZE, 170);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_YSIZE, 94);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_BGCOLOR, clrBlack);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_BACK, false);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_SELECTABLE, false);
   HUD_Label("title", 16, 24, "CandleSenseSwing", clrGold);
   HUD_Update();
  }

void HUD_Update()
  {
   if(!ShowHUD) return;
   double subtotal = g_hudEarned + g_hudLost;
   HUD_Label("trades",   16, 42, StringFormat("Trades: %d", g_hudTrades), clrWhite);
   HUD_Label("open",     16, 58, StringFormat("Open now: %d / %d", CountMyOpenTrades(), MaxOpenTrades), clrSilver);
   HUD_Label("earned",   16, 74, StringFormat("Earned: %.2f", g_hudEarned), clrLimeGreen);
   HUD_Label("lost",     16, 90, StringFormat("Lost: %.2f", g_hudLost), clrTomato);
   HUD_Label("subtotal", 16, 106, StringFormat("Subtotal: %.2f", subtotal), subtotal >= 0 ? clrLimeGreen : clrTomato);
  }

void HUD_Remove() { ObjectsDeleteAll(0, HUD_PREFIX); }

//================================= Helpers ===================================
double Pt() { return SymbolInfoDouble(_Symbol, SYMBOL_POINT); }

double EMA(int shift=1)
  {
   if(g_hEMA == INVALID_HANDLE) return 0;
   double buf[];
   if(CopyBuffer(g_hEMA, 0, shift, 1, buf) <= 0) return 0;
   return buf[0];
  }

// 1 = up, -1 = down, 0 = no clear trend. The EMA must have risen (or fallen) for
// TrendConfirmBars bars in a row - a simple, cheap slope check instead of a
// full swing-structure scan, matching the "just go with where the chart's going" idea.
int TrendDirection()
  {
   if(g_hEMA == INVALID_HANDLE) return 0;
   double buf[];
   if(CopyBuffer(g_hEMA, 0, 1, TrendConfirmBars + 1, buf) <= 0) return 0;
   ArraySetAsSeries(buf, true);
   bool up = true, down = true;
   for(int i = 0; i < TrendConfirmBars; i++)
     {
      if(buf[i] <= buf[i+1]) up = false;
      if(buf[i] >= buf[i+1]) down = false;
     }
   if(up) return 1;
   if(down) return -1;
   return 0;
  }

void CheckNewDay()
  {
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", dt.year, dt.mon, dt.day));
   if(today != g_dayStamp)
     {
      g_dayStamp = today;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_BALANCE);
     }
  }

bool DailyLimitHit()
  {
   if(g_dayStartEquity <= 0) return false;
   double loss = g_dayStartEquity - AccountInfoDouble(ACCOUNT_EQUITY);
   return loss >= g_dayStartEquity * DailyLossLimitPct / 100.0;
  }

int CountMyOpenTrades()
  {
   int n = 0;
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == MagicNumber && PositionGetString(POSITION_SYMBOL) == _Symbol)
         n++;
     }
   return n;
  }

// Lot size per trade so that MaxOpenTrades positions, ALL hit at once by their SL,
// lose no more than MaxTotalRiskPct of balance in total - not a flat % per trade,
// which would let worst-case loss grow unbounded as more trades stack.
double LotsPerStackedTrade(double entry, double stop, bool isBuy)
  {
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   ENUM_ORDER_TYPE ot = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   double testLot = minLot > 0 ? minLot : 0.01;
   double pnl = 0;
   if(!OrderCalcProfit(ot, _Symbol, testLot, entry, stop, pnl) || pnl == 0)
      return minLot;
   double lossPerTestLot = MathAbs(pnl);

   double totalRiskBudget = AccountInfoDouble(ACCOUNT_BALANCE) * MaxTotalRiskPct / 100.0;
   double perTradeBudget  = totalRiskBudget / MathMax(1, MaxOpenTrades);

   double lots = perTradeBudget / lossPerTestLot * testLot;
   lots = MathFloor(lots / step) * step;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return NormalizeDouble(lots, 2);
  }

//================================== Entries ===================================
void TryEnter()
  {
   if(CountMyOpenTrades() >= MaxOpenTrades) { return; }
   if(DailyLimitHit()) { Print("CSSwing skip: daily loss limit hit"); return; }

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID)) / Pt();
   if(spread > MaxSpreadPoints) { PrintFormat("CSSwing skip: spread %.1f > max %.1f", spread, MaxSpreadPoints); return; }

   int dir = TrendDirection();
   if(dir == 0) { return; } // no clear trend this bar - stay out, no log spam

   bool isBuy = (dir == 1);
   double point = Pt();
   double entry = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // Only stack another trade once price has moved far enough in the trend's
   // direction since the last entry (or the trend just flipped direction).
   if(g_lastEntryDir == dir && g_lastEntryPrice > 0)
     {
      double moved = isBuy ? (entry - g_lastEntryPrice) / point : (g_lastEntryPrice - entry) / point;
      if(moved < MinStackPoints) return;
     }

   double sl = isBuy ? entry - SL_Points*point : entry + SL_Points*point;
   double tp = isBuy ? entry + TP_Points*point : entry - TP_Points*point;

   double stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   if(MathAbs(entry - sl) < stopsLevel || MathAbs(entry - tp) < stopsLevel) return;

   double lots = LotsPerStackedTrade(entry, sl, isBuy);
   if(lots <= 0) return;

   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = isBuy ? trade.Buy(lots, _Symbol, entry, sl, tp, "CS-Swing")
                   : trade.Sell(lots, _Symbol, entry, sl, tp, "CS-Swing");
   if(ok)
     {
      g_lastEntryPrice = entry;
      g_lastEntryDir = dir;
      PrintFormat("CandleSenseSwing: %s %.2f lots @ %.2f sl %.2f tp %.2f (open %d/%d)",
                  isBuy?"BUY":"SELL", lots, entry, sl, tp, CountMyOpenTrades()+1, MaxOpenTrades);
     }
  }

//=========================== Track closed deals ============================
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) + HistoryDealGetDouble(trans.deal, DEAL_SWAP) + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   g_hudTrades++;
   if(profit >= 0) g_hudEarned += profit; else g_hudLost += profit;
   HUD_Update();
  }

//================================== Lifecycle ====================================
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   g_dayStamp = 0;
   CheckNewDay();

   g_hEMA = iMA(_Symbol, EntryTF, TrendEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(g_hEMA == INVALID_HANDLE)
     {
      Print("CandleSenseSwing: failed to create the EMA handle - check symbol/timeframe.");
      return INIT_FAILED;
     }

   HUD_Create();
   PrintFormat("CandleSenseSwing v1.00 loaded on %s %s. SL %.0f / TP %.0f points, max %d open, risk cap %.1f%%.",
               _Symbol, EnumToString(EntryTF), SL_Points, TP_Points, MaxOpenTrades, MaxTotalRiskPct);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_hEMA != INVALID_HANDLE) IndicatorRelease(g_hEMA);
   HUD_Remove();
  }

void OnTick()
  {
   CheckNewDay();

   static datetime lastBarTime = 0;
   datetime curBarTime = iTime(_Symbol, EntryTF, 0);
   if(curBarTime == lastBarTime) { HUD_Update(); return; }
   lastBarTime = curBarTime;

   TryEnter();
   HUD_Update();
  }
//+------------------------------------------------------------------+
