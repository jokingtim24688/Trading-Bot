//+------------------------------------------------------------------+
//| CandleSenseStart.mq5                                             |
//| A gold EA built specifically for a small starting balance        |
//| (around $100) and for someone running their first EA.            |
//|                                                                    |
//| Every design choice here comes from a measurement in this repo    |
//| (ea/*.py), not from taste:                                        |
//|                                                                    |
//| 1. WIDE TARGETS. Entering at the ask puts every trade ~45 points  |
//|    down on gold straight away. With a 150/200 stop/target the     |
//|    strategy must beat random by 12.9% on every trade; at 250/625  |
//|    it only needs 5.1%. Widening the target is the cheapest        |
//|    improvement a small account can make (ea/small_account_study). |
//| 2. FEW TRADES. Every trade pays the spread again. Simulating the  |
//|    same bot at higher frequency lost linearly more money - at one |
//|    trade a second it lost $62.7M of a $5M account in 5.8 hours    |
//|    (ea/frequency_study.py). So this EA waits for its setup.       |
//| 3. EXPECTANCY, NOT WIN RATE. A 600/20 stop/target wins 94.8% of   |
//|    trades and still loses money (ea/winrate_vs_money.py). This EA |
//|    deliberately takes a ~35-40% win rate at 1:2.5 instead.        |
//| 4. AUTO GMT. The killzone filter in CandleSenseICT silently       |
//|    blocked every trade because the broker's clock was not GMT.    |
//|    This one works the offset out by itself at start-up.           |
//| 5. SURVIVAL FIRST. From $100 you cannot recover from ruin, so     |
//|    there is a daily loss limit, a pause after consecutive losses, |
//|    and a hard floor that stops the EA entirely.                   |
//| 6. SIZED FOR $5 A TRADE (v1.10). 5% risk is roughly half-Kelly IF |
//|    the strategy wins ~35%; at 30% it is 2.5x over-betting and      |
//|    turns a $117 year into a $75 one (ea/betsize_study.py). Run it  |
//|    at RiskPercent 1-2 until 50 demo trades have shown the real     |
//|    win rate, THEN raise it to 5. Expect ~60% drawdowns at 5%.      |
//|                                                                    |
//| Strategy: trend-aligned pullback. The H1 EMA50/200 sets the       |
//| direction; it then waits for price to pull back to the M15 EMA20  |
//| and close back in the trend's direction. Stops are ATR-based.     |
//|                                                                    |
//| Run it on DEMO first. Nothing here guarantees profit.             |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.11"
#property description "Gold EA for small accounts: trend pullback, wide targets, auto-GMT sessions, hard loss protection."
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//================================= Inputs ==================================
input group "=== Risk (the important part) ==="
input double RiskPercent        = 5.0;    // % of balance risked per trade ($5 on $100; see ea/betsize_study.py)
input double MaxDailyLossPct    = 15.0;   // Stop trading for the day after losing this % (3 losses at 5%)
input int    PauseAfterLosses   = 3;      // Pause for the day after this many losses in a row
input double StopIfBalanceBelow = 50.0;   // Hard floor: stop the EA entirely under this balance

input group "=== Stop & target ==="
input double ATR_SL_Mult        = 1.5;    // Stop = ATR x this
input double MinStopPoints      = 250;    // ...never tighter (spread is then 18% of the stop, not 30%)
input double RewardRatio        = 3.5;    // Target = stop x this (wider beats the fixed spread toll)
input double MaxSpreadVsStop    = 0.25;   // Skip if spread is more than this share of the stop

input group "=== Setup ==="
input ENUM_TIMEFRAMES TrendTF   = PERIOD_H1;   // Timeframe that sets the trend
input ENUM_TIMEFRAMES EntryTF   = PERIOD_M15;  // Timeframe the pullback is found on
input int    EMA_Fast           = 50;     // H1 fast EMA
input int    EMA_Slow           = 200;    // H1 slow EMA
input int    PullbackEMA        = 20;     // M15 EMA price pulls back to
input int    ATR_Period         = 14;

input group "=== Sessions (offset found automatically) ==="
input bool   UseSessions        = true;   // Only trade the active London/NY hours
input int    SessionStartGMT    = 7;      // London open
input int    SessionEndGMT      = 20;     // NY afternoon

input group "=== Protecting a winner ==="
input bool   UseBreakEven       = true;   // Move the stop to entry once ahead
input double BE_TriggerR        = 1.0;    // ...once profit reaches this x risk
input bool   UseTrailing        = true;   // Then trail the stop
input double Trail_ATR_Mult     = 2.0;

input group "=== Other ==="
input int    MaxOpenTrades      = 1;      // One at a time: $100 has margin for ~2 on gold
input int    MagicNumber        = 260932;
input bool   ShowHUD            = true;

//================================= State ====================================
int    g_hEMAfast = INVALID_HANDLE, g_hEMAslow = INVALID_HANDLE;
int    g_hPull = INVALID_HANDLE, g_hATR = INVALID_HANDLE;
int    g_gmtOffset = 0;
double g_dayStartBalance = 0, g_startBalance = 0;
datetime g_dayStamp = 0;
int    g_lossStreak = 0, g_tradesToday = 0;
bool   g_halted = false;
string g_status = "starting";

int    g_trades = 0, g_wins = 0;
double g_earned = 0, g_lost = 0;
#define HUD "CSSTART_"

int CountOpen();

//================================= HUD =======================================
void Lbl(string n, int y, string t, color c)
  {
   string f = HUD + n;
   if(ObjectFind(0, f) < 0)
     {
      ObjectCreate(0, f, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, f, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, f, OBJPROP_XDISTANCE, 16);
      ObjectSetInteger(0, f, OBJPROP_YDISTANCE, y);
      ObjectSetInteger(0, f, OBJPROP_FONTSIZE, 10);
      ObjectSetString(0, f, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, f, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, f, OBJPROP_HIDDEN, true);
     }
   ObjectSetString(0, f, OBJPROP_TEXT, t);
   ObjectSetInteger(0, f, OBJPROP_COLOR, c);
  }

void HUD_Create()
  {
   if(!ShowHUD) return;
   ObjectCreate(0, HUD+"bg", OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_XDISTANCE, 8);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_YDISTANCE, 18);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_XSIZE, 350);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_YSIZE, 182);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_BGCOLOR, clrBlack);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_BACK, false);
   ObjectSetInteger(0, HUD+"bg", OBJPROP_SELECTABLE, false);
   HUD_Update();
  }

void HUD_Update()
  {
   if(!ShowHUD) return;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double net = g_earned + g_lost;
   double grow = g_startBalance > 0 ? (bal/g_startBalance - 1)*100 : 0;
   double wr = g_trades > 0 ? 100.0*g_wins/g_trades : 0;
   Lbl("t",  24, "CandleSenseStart  (small-account gold EA)", clrGold);
   Lbl("bal",42, StringFormat("Balance: $%.2f   (%+.1f%% since start)", bal, grow), grow>=0?clrLimeGreen:clrTomato);
   Lbl("res",58, StringFormat("Trades: %d   Win rate: %.0f%%   (needs %.0f%%)",
                 g_trades, wr, 100.0/(1.0+RewardRatio)), clrWhite);
   Lbl("pl", 74, StringFormat("Earned: $%.2f    Lost: $%.2f", g_earned, g_lost), clrSilver);
   Lbl("net",90, StringFormat("Net: $%.2f", net), net>=0?clrLimeGreen:clrTomato);
   Lbl("rk",106, StringFormat("Risking %.1f%% = $%.2f per trade", RiskPercent, bal*RiskPercent/100), clrSilver);
   Lbl("dy",122, StringFormat("Today: %d trades, %d losses in a row", g_tradesToday, g_lossStreak), clrSilver);
   Lbl("gmt",138,StringFormat("Broker clock = GMT%+d (found automatically)", g_gmtOffset), clrSilver);
   Lbl("st",154, "Status: " + g_status, g_halted ? clrTomato : clrKhaki);
  }

void HUD_Remove() { ObjectsDeleteAll(0, HUD); }

//================================= Helpers ===================================
double Pt() { return SymbolInfoDouble(_Symbol, SYMBOL_POINT); }

double Buf(int h, int shift=1)
  {
   if(h == INVALID_HANDLE) return 0;
   double b[];
   if(CopyBuffer(h, 0, shift, 1, b) <= 0) return 0;
   return b[0];
  }

// Works out the broker's GMT offset from its own server time. This is the bug that
// silently stopped CandleSenseICT from ever trading - here it is not a setting to get wrong.
void DetectGMT()
  {
   datetime srv = TimeTradeServer(), gmt = TimeGMT();
   if(srv <= 0 || gmt <= 0) { g_gmtOffset = 0; return; }
   g_gmtOffset = (int)MathRound((double)(srv - gmt)/3600.0);
  }

bool InSession()
  {
   if(!UseSessions) return true;
   MqlDateTime dt; TimeToStruct(TimeTradeServer() - g_gmtOffset*3600, dt);
   if(dt.day_of_week == 0 || dt.day_of_week == 6) return false;
   return dt.hour >= SessionStartGMT && dt.hour < SessionEndGMT;
  }

void CheckNewDay()
  {
   MqlDateTime dt; TimeToStruct(TimeTradeServer(), dt);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", dt.year, dt.mon, dt.day));
   if(today != g_dayStamp)
     {
      g_dayStamp = today;
      g_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_lossStreak = 0;
      g_tradesToday = 0;
     }
  }

int CountOpen()
  {
   int n = 0;
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == MagicNumber && PositionGetString(POSITION_SYMBOL) == _Symbol) n++;
     }
   return n;
  }

// Risk-based size from the CURRENT balance, so the account compounds as it grows.
double Lots(double entry, double stop, bool isBuy)
  {
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double pnl = 0;
   double testLot = minLot > 0 ? minLot : 0.01;
   if(!OrderCalcProfit(isBuy?ORDER_TYPE_BUY:ORDER_TYPE_SELL, _Symbol, testLot, entry, stop, pnl) || pnl == 0)
      return minLot;

   double risk = AccountInfoDouble(ACCOUNT_BALANCE) * RiskPercent/100.0;
   double lots = risk / MathAbs(pnl) * testLot;
   lots = MathFloor(lots/step)*step;
   lots = MathMax(minLot, MathMin(maxLot, lots));

   // Skip, don't just warn, when even the minimum lot would risk far more than RiskPercent.
   // Replaying v1.10 on real 2026 gold: M15 ATR stops ran 1,100-2,100 points, so 0.01 lots
   // risked $11-21 (11-21% of $100) instead of 5%, and the account fell to $43 in 3 weeks.
   double realRisk = MathAbs(pnl)/testLot*lots;
   if(lots <= minLot && realRisk > risk*1.5)
     {
      g_status = StringFormat("skipped: smallest lot would risk $%.2f (%.0f%%), you set %.0f%%",
                              realRisk, 100*realRisk/AccountInfoDouble(ACCOUNT_BALANCE), RiskPercent);
      return 0;
     }
   return NormalizeDouble(lots, 2);
  }

//================================== Entry ====================================
// Returns false only when indicator data isn't loaded yet, so OnTick retries on the very next
// tick instead of waiting for the next M15 bar. Any other outcome (trade, skip, no setup)
// returns true and the bar counts as checked.
bool TryEnter()
  {
   if(g_halted) return true;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);

   if(bal < StopIfBalanceBelow)
     { g_halted = true; g_status = StringFormat("STOPPED: balance under $%.0f", StopIfBalanceBelow);
       Print("CSStart: ", g_status); return true; }
   if(CountOpen() >= MaxOpenTrades) { g_status = "in a trade, managing it"; return true; }
   if(g_dayStartBalance > 0 && (g_dayStartBalance - bal) >= g_dayStartBalance*MaxDailyLossPct/100.0)
     { g_status = StringFormat("done for today: hit the %.0f%% daily loss limit", MaxDailyLossPct); return true; }
   if(g_lossStreak >= PauseAfterLosses)
     { g_status = StringFormat("paused: %d losses in a row, back tomorrow", g_lossStreak); return true; }
   if(!InSession()) { g_status = "outside London/NY hours - waiting"; return true; }

   double point = Pt();
   double atr = Buf(g_hATR);
   if(atr <= 0) { g_status = "waiting for indicator data"; return false; }

   double stopDist = MathMax(atr*ATR_SL_Mult, MinStopPoints*point);
   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID));
   if(spread > stopDist*MaxSpreadVsStop)
     { g_status = StringFormat("spread %.0f pts too wide vs %.0f pt stop", spread/point, stopDist/point); return true; }

   double fast = Buf(g_hEMAfast), slow = Buf(g_hEMAslow);
   if(fast == 0 || slow == 0) { g_status = "waiting for trend data"; return false; }
   int bias = fast > slow ? 1 : -1;

   // Pullback: the previous bar dipped to/through the M15 EMA20 and this one closed back with the trend.
   double ema = Buf(g_hPull, 1), emaPrev = Buf(g_hPull, 2);
   double c1 = iClose(_Symbol, EntryTF, 1), c2 = iClose(_Symbol, EntryTF, 2);
   double l1 = iLow(_Symbol, EntryTF, 1),  h1 = iHigh(_Symbol, EntryTF, 1);
   if(ema == 0) { g_status = "waiting for pullback data"; return false; }

   bool setup = false;
   if(bias == 1  && l1 <= ema && c1 > ema && c2 <= emaPrev) setup = true;
   if(bias == -1 && h1 >= ema && c1 < ema && c2 >= emaPrev) setup = true;
   if(!setup)
     { g_status = StringFormat("%s trend - waiting for a pullback", bias==1?"up":"down"); return true; }

   bool isBuy = (bias == 1);
   double entry = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = isBuy ? entry - stopDist : entry + stopDist;
   double tp = isBuy ? entry + stopDist*RewardRatio : entry - stopDist*RewardRatio;

   double stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL)*point;
   if(stopDist < stopsLevel) { g_status = "broker's minimum stop is wider than ours"; return true; }

   double lots = Lots(entry, sl, isBuy);
   if(lots <= 0) return true;                      // too big for this account - skipped
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double marginNeeded = 0;
   if(OrderCalcMargin(isBuy?ORDER_TYPE_BUY:ORDER_TYPE_SELL, _Symbol, lots, entry, marginNeeded)
      && marginNeeded > freeMargin)
     { g_status = StringFormat("not enough margin ($%.2f needed, $%.2f free)", marginNeeded, freeMargin); return true; }

   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = isBuy ? trade.Buy(lots, _Symbol, entry, sl, tp, "CS-Start")
                   : trade.Sell(lots, _Symbol, entry, sl, tp, "CS-Start");
   if(ok)
     {
      g_tradesToday++;
      double pnl = 0;
      OrderCalcProfit(isBuy?ORDER_TYPE_BUY:ORDER_TYPE_SELL, _Symbol, lots, entry, sl, pnl);
      g_status = StringFormat("opened %s %.2f lots, risking $%.2f", isBuy?"BUY":"SELL", lots, MathAbs(pnl));
      PrintFormat("CSStart: %s %.2f lots @ %.2f  sl %.2f (%.0f pts)  tp %.2f (%.0f pts)",
                  isBuy?"BUY":"SELL", lots, entry, sl, stopDist/point, tp, stopDist*RewardRatio/point);
     }
   else
     {
      g_status = StringFormat("order refused: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      Print("CSStart: ", g_status);
     }
   return true;
  }

//============================== Manage trades =================================
void Manage()
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber || PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      bool isBuy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double risk = MathAbs(entry - sl);
      if(risk <= 0) continue;
      double r = isBuy ? (price-entry)/risk : (entry-price)/risk;

      double newSl = sl;
      if(UseBreakEven && r >= BE_TriggerR)
        {
         double be = isBuy ? entry + 10*Pt() : entry - 10*Pt();
         if((isBuy && be > newSl) || (!isBuy && be < newSl)) newSl = be;
        }
      if(UseTrailing && r >= BE_TriggerR)
        {
         double atr = Buf(g_hATR);
         double tr = isBuy ? price - atr*Trail_ATR_Mult : price + atr*Trail_ATR_Mult;
         if((isBuy && tr > newSl) || (!isBuy && tr < newSl)) newSl = tr;
        }
      if(newSl != sl) trade.PositionModify(ticket, newSl, tp);
     }
  }

//============================ Learn from each close ===========================
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double p = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
            + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
            + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   g_trades++;
   if(p >= 0) { g_earned += p; g_wins++; g_lossStreak = 0; }
   else       { g_lost += p; g_lossStreak++; }
   HUD_Update();
  }

//================================ Lifecycle ===================================
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   g_startBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_dayStamp = 0;
   DetectGMT();
   CheckNewDay();

   g_hEMAfast = iMA(_Symbol, TrendTF, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   g_hEMAslow = iMA(_Symbol, TrendTF, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   g_hPull    = iMA(_Symbol, EntryTF, PullbackEMA, 0, MODE_EMA, PRICE_CLOSE);
   g_hATR     = iATR(_Symbol, EntryTF, ATR_Period);
   if(g_hEMAfast==INVALID_HANDLE || g_hEMAslow==INVALID_HANDLE || g_hPull==INVALID_HANDLE || g_hATR==INVALID_HANDLE)
     { Print("CSStart: could not create indicators"); return INIT_FAILED; }

   HUD_Create();
   PrintFormat("CandleSenseStart v1.00 on %s. Balance $%.2f, risking %.1f%% per trade, "
               "stop x%.1f ATR (min %.0f pts), target x%.1f. Broker clock = GMT%+d.",
               _Symbol, g_startBalance, RiskPercent, ATR_SL_Mult, MinStopPoints, RewardRatio, g_gmtOffset);
   if(g_startBalance < 80)
      Print("CSStart WARNING: under $80 the minimum 0.01 lot risks more than ", RiskPercent,
            "% per trade. See ea/small_account_study.py - $100+ is the workable floor on gold.");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_hEMAfast!=INVALID_HANDLE) IndicatorRelease(g_hEMAfast);
   if(g_hEMAslow!=INVALID_HANDLE) IndicatorRelease(g_hEMAslow);
   if(g_hPull!=INVALID_HANDLE)    IndicatorRelease(g_hPull);
   if(g_hATR!=INVALID_HANDLE)     IndicatorRelease(g_hATR);
   HUD_Remove();
  }

void OnTick()
  {
   CheckNewDay();
   Manage();

   // No warm-up: MT5 loads the chart history when the EA is attached, so every indicator is
   // ready at once. The first tick after launch checks for a setup immediately, and if the
   // terminal is still loading history it retries on each tick rather than waiting a bar.
   static datetime lastBar = 0;
   datetime cur = iTime(_Symbol, EntryTF, 0);
   if(cur != lastBar && TryEnter()) lastBar = cur;
   HUD_Update();
  }
//+------------------------------------------------------------------+
