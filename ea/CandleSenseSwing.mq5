//+------------------------------------------------------------------+
//| CandleSenseSwing.mq5                                             |
//| Trades every swing of the chart, both ways, stacking trades       |
//| with a small fixed stop and target in points.                     |
//|                                                                    |
//| v2: no confidence filter any more. v1 waited for an EMA to slope  |
//| the same way for 3 bars, so it sat out most swings. Now it reads  |
//| the chart's own swing highs and lows (a bar whose high/low beats  |
//| SwingStrength bars on each side):                                 |
//|  - last confirmed swing was a LOW  -> the chart is swinging UP,   |
//|    so it buys;                                                    |
//|  - last confirmed swing was a HIGH -> swinging DOWN, so it sells. |
//| There is always a current swing, so it always has a direction.   |
//| The first trade of each new swing goes in at once; more trades    |
//| stack every MinStackPoints the price travels with that swing.     |
//|                                                                    |
//| Many trades can be open at once, so MaxTotalRiskPct caps what ALL |
//| open trades would lose together if every stop hit at the same    |
//| time, split across MaxOpenTrades.                                 |
//|                                                                    |
//| Test it in the Strategy Tester and on a DEMO account first.       |
//| Nothing here guarantees profit.                                   |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "2.00"
#property description "Trades every swing both ways: fixed SL/TP in points, stacks up to N trades, risk-capped sizing."
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//================================= Inputs ==================================
input group "=== Swings ==="
input ENUM_TIMEFRAMES EntryTF        = PERIOD_M1;   // Timeframe the swings are read on
input int    SwingStrength           = 2;           // A swing high/low must beat this many bars on each side
input int    SwingLookback           = 200;         // Bars searched for the latest swing

input group "=== Stacking ==="
input double SL_Points               = 150;         // Fixed stop loss, points
input double TP_Points               = 200;         // Fixed take profit, points
input double MinStackPoints          = 60;          // Price must move this far with the swing before stacking another trade
input int    MaxOpenTrades           = 60;          // Max concurrent trades (this EA's own magic number only)

input group "=== Sizing & risk ==="
input double MaxTotalRiskPct         = 8.0;         // Worst case: if ALL open trades hit SL together, cap the loss at this % of balance
input double MaxSpreadPoints         = 40;          // Refuse entries when spread exceeds this
input double DailyLossLimitPct       = 10.0;        // Stop trading for the day after this % balance loss
input int    MagicNumber             = 260931;      // Order magic number

input group "=== HUD ==="
input bool   ShowHUD                 = true;        // Show the on-chart panel

//================================= State ====================================
double   g_dayStartEquity = 0;
datetime g_dayStamp        = 0;
double   g_lastEntryPrice  = 0;
int      g_lastEntryDir    = 0;   // 1 buy, -1 sell, 0 none yet

int      g_legDir          = 0;   // 1 swinging up, -1 swinging down
double   g_legPivot        = 0;   // price of the swing low/high the current leg started from
datetime g_legPivotTime    = 0;   // bar time of that swing point (changes = a new swing)

int    g_hudTrades = 0, g_hudWins = 0;
double g_hudEarned = 0, g_hudLost = 0;
#define HUD_PREFIX "CSSWING_HUD_"

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
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_XSIZE, 210);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_YSIZE, 164);
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
   string swing = g_legDir == 1 ? StringFormat("UP from %.2f", g_legPivot)
                : g_legDir == -1 ? StringFormat("DOWN from %.2f", g_legPivot) : "finding swing...";
   double winRate = g_hudTrades > 0 ? 100.0 * g_hudWins / g_hudTrades : 0;
   HUD_Label("swing",    16, 42,  "Swing: " + swing, g_legDir == 1 ? clrLimeGreen : g_legDir == -1 ? clrTomato : clrSilver);
   HUD_Label("trades",   16, 58,  StringFormat("Trades: %d", g_hudTrades), clrWhite);
   HUD_Label("winrate",  16, 74,  StringFormat("Win rate: %.0f%% (need 43%%)", winRate), clrSilver);
   HUD_Label("open",     16, 90,  StringFormat("Open now: %d / %d", CountMyOpenTrades(), MaxOpenTrades), clrSilver);
   HUD_Label("earned",   16, 106, StringFormat("Earned: %.2f", g_hudEarned), clrLimeGreen);
   HUD_Label("lost",     16, 122, StringFormat("Lost: %.2f", g_hudLost), clrTomato);
   HUD_Label("subtotal", 16, 138, StringFormat("Subtotal: %.2f", subtotal), subtotal >= 0 ? clrLimeGreen : clrTomato);
  }

void HUD_Remove() { ObjectsDeleteAll(0, HUD_PREFIX); }

//================================= Helpers ===================================
double Pt() { return SymbolInfoDouble(_Symbol, SYMBOL_POINT); }

bool IsSwingHigh(int i)
  {
   double h = iHigh(_Symbol, EntryTF, i);
   for(int k = 1; k <= SwingStrength; k++)
      if(iHigh(_Symbol, EntryTF, i - k) >= h || iHigh(_Symbol, EntryTF, i + k) > h) return false;
   return true;
  }

bool IsSwingLow(int i)
  {
   double l = iLow(_Symbol, EntryTF, i);
   for(int k = 1; k <= SwingStrength; k++)
      if(iLow(_Symbol, EntryTF, i - k) <= l || iLow(_Symbol, EntryTF, i + k) < l) return false;
   return true;
  }

// Finds the latest confirmed swing point. A swing low means the chart is now swinging up,
// a swing high means it's swinging down. Bars that are both (outside bars) are skipped.
bool UpdateLeg()
  {
   int last = MathMin(SwingLookback, iBars(_Symbol, EntryTF) - SwingStrength - 1);
   for(int i = SwingStrength + 1; i < last; i++)
     {
      bool hi = IsSwingHigh(i), lo = IsSwingLow(i);
      if(hi == lo) continue;
      g_legDir       = lo ? 1 : -1;
      g_legPivot     = lo ? iLow(_Symbol, EntryTF, i) : iHigh(_Symbol, EntryTF, i);
      datetime t     = iTime(_Symbol, EntryTF, i);
      bool isNew     = (t != g_legPivotTime);
      g_legPivotTime = t;
      return isNew;
     }
   return false;
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

   double perTradeBudget = AccountInfoDouble(ACCOUNT_BALANCE) * MaxTotalRiskPct / 100.0 / MathMax(1, MaxOpenTrades);
   double lots = perTradeBudget / lossPerTestLot * testLot;
   lots = MathFloor(lots / step) * step;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return NormalizeDouble(lots, 2);
  }

//================================== Entries ===================================
void TryEnter()
  {
   bool newSwing = UpdateLeg();
   if(newSwing)
     {
      PrintFormat("CSSwing: new swing %s from %.2f", g_legDir == 1 ? "UP" : "DOWN", g_legPivot);
      g_lastEntryPrice = 0;   // first trade of a new swing goes in at once
     }
   if(g_legDir == 0) { Print("CSSwing skip: no swing found yet (not enough bars)"); return; }

   if(CountMyOpenTrades() >= MaxOpenTrades) return;
   if(DailyLimitHit()) { Print("CSSwing skip: daily loss limit hit"); return; }

   double point = Pt();
   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID)) / point;
   if(spread > MaxSpreadPoints) { PrintFormat("CSSwing skip: spread %.1f > max %.1f", spread, MaxSpreadPoints); return; }

   int dir = g_legDir;
   bool isBuy = (dir == 1);
   double entry = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(g_lastEntryDir == dir && g_lastEntryPrice > 0)
     {
      double moved = isBuy ? (entry - g_lastEntryPrice) / point : (g_lastEntryPrice - entry) / point;
      if(moved < MinStackPoints) return;
     }

   double sl = isBuy ? entry - SL_Points*point : entry + SL_Points*point;
   double tp = isBuy ? entry + TP_Points*point : entry - TP_Points*point;

   double stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   if(MathAbs(entry - sl) < stopsLevel || MathAbs(entry - tp) < stopsLevel)
     { PrintFormat("CSSwing skip: SL/TP closer than the broker's stop level (%.0f pts)", stopsLevel/point); return; }

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
                  isBuy?"BUY":"SELL", lots, entry, sl, tp, CountMyOpenTrades(), MaxOpenTrades);
     }
   else
      PrintFormat("CSSwing: order failed, retcode %d (%s)", trade.ResultRetcode(), trade.ResultRetcodeDescription());
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
   if(profit >= 0) { g_hudEarned += profit; g_hudWins++; } else g_hudLost += profit;
   HUD_Update();
  }

//================================== Lifecycle ====================================
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   g_dayStamp = 0;
   CheckNewDay();
   UpdateLeg();
   HUD_Create();
   PrintFormat("CandleSenseSwing v2.00 loaded on %s %s. Trades every swing, SL %.0f / TP %.0f points, max %d open.",
               _Symbol, EnumToString(EntryTF), SL_Points, TP_Points, MaxOpenTrades);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { HUD_Remove(); }

void OnTick()
  {
   CheckNewDay();

   static datetime lastBarTime = 0;
   datetime curBarTime = iTime(_Symbol, EntryTF, 0);
   if(curBarTime != lastBarTime)
     {
      lastBarTime = curBarTime;
      TryEnter();
     }
   HUD_Update();
  }
//+------------------------------------------------------------------+
