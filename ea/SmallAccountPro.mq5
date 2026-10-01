//+------------------------------------------------------------------+
//|                                              SmallAccountPro.mq5 |
//| Trend-pullback + momentum confluence EA for small accounts       |
//| ($100 start, minimum $5 risk per trade). Built from the user's   |
//| specification; sizing uses OrderCalcProfit (the broker's own     |
//| money maths) with tick value only as a fallback, because tick    |
//| value was ~10x off on gold for an earlier EA in this repo.       |
//| Test in the Strategy Tester and on a DEMO account first.         |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.03"
#property description "EMA 21/50/200 trend pullback with RSI and Bollinger confirmation, $5 minimum risk, dollar break-even and trailing, daily loss breaker, weekly goal HUD."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\AccountInfo.mqh>

//================================ Inputs =================================
input group "=== Start-up ==="
input int    InpStartupDelaySeconds        = 60;     // Seconds to wait after attaching (0 = trade at once)
input bool   InpTradeImmediatelyAfterDelay = true;   // Open one trade on the current bias when the delay ends

input group "=== Risk & targets ==="
input double InpMinDollarRiskPerTrade = 5.0;     // Minimum $ lost if the stop is hit
input double InpRiskPercentOfBalance  = 0.0;     // 0 = fixed $ risk; e.g. 0.5 = risk 0.5% of balance (compounds, never below the minimum)
input bool   InpUseRiskLadder         = true;    // Risk ladder: $5 per $100 of balance, then a flat top amount (overrides the % above)
input double InpLadderStepBalance     = 100.0;   // Ladder: each step of this much balance...
input double InpLadderRiskPerStep     = 5.0;     // ...adds this much risk ($100 -> $5, $200 -> $10, ...)
input int    InpLadderSteps           = 5;       // Steps before the top ($500-$599 -> $25)
input double InpLadderTopRisk         = 50.0;    // Risk once the balance is past the last step ($600+)
input double InpRiskRewardRatio       = 1.8;     // Take profit = stop distance x this
input double InpWeeklyProfitTarget    = 100.0;   // Weekly profit goal in account currency
input bool   InpPauseAtWeeklyTarget   = false;   // Stop opening trades once the rolling 7-day goal is met
input double InpATRMultiplier         = 1.5;     // Stop = ATR(14) x this, before clamping
input int    InpMinSLPoints           = 100;     // Smallest stop allowed, points
input int    InpMaxSLPoints           = 500;     // Largest stop allowed, points
input double InpMaxMarginShare        = 0.80;    // Never use more than this share of free margin

input group "=== Protection ==="
input double InpBreakEvenTriggerUSD = 2.50;   // Move stop to lock profit once a trade is up this much
input double InpBreakEvenLockUSD    = 0.50;   // ...locking in this much
input double InpTrailStartUSD       = 4.00;   // Start trailing once a trade is up this much
input double InpTrailStepUSD        = 1.50;   // Trail this many $ behind price
input int    InpMaxSpreadPoints     = 50;     // No new entries above this spread
input double InpMaxDailyLossUSD     = 15.0;   // Halt new entries for the day after losing this much

input group "=== Strategy ==="
input int    InpEMAFast      = 21;
input int    InpEMAMid       = 50;
input int    InpEMASlow      = 200;
input int    InpRSIPeriod    = 14;
input int    InpBBPeriod     = 20;
input double InpBBDeviation  = 2.0;
input int    InpATRPeriod    = 14;
input double InpBuyRSIMin    = 45.0;
input double InpBuyRSIMax    = 68.0;
input double InpSellRSIMin   = 32.0;
input double InpSellRSIMax   = 55.0;
input double InpTouchATR     = 0.10;  // "Near" the EMA21/middle band = within this x ATR
input double InpSlopeATR     = 0.05;  // "Strong slope" = EMA21 moved this x ATR in one bar

input group "=== Other ==="
input long   InpMagic          = 777100;
input int    InpSlippagePoints = 30;

//================================ Objects ================================
CTrade        g_trade;
CPositionInfo g_pos;
CSymbolInfo   g_sym;
CAccountInfo  g_acc;

int g_hEMAFast = INVALID_HANDLE;
int g_hEMAMid  = INVALID_HANDLE;
int g_hEMASlow = INVALID_HANDLE;
int g_hRSI     = INVALID_HANDLE;
int g_hBB      = INVALID_HANDLE;
int g_hATR     = INVALID_HANDLE;

double g_emaFast[], g_emaMid[], g_emaSlow[], g_rsi[], g_bbUp[], g_bbMid[], g_bbLow[], g_atr[];
MqlRates g_rates[];

datetime g_startTime        = 0;
bool     g_initialTradeDone = false;
datetime g_lastBarTime      = 0;
string   g_lastAction       = "none yet";

//================================ Helpers ================================
bool WarmUpOver()
  {
   return (TimeCurrent() - g_startTime) >= InpStartupDelaySeconds;
  }

int WarmUpRemaining()
  {
   long left = (long)InpStartupDelaySeconds - (long)(TimeCurrent() - g_startTime);
   if(left < 0) left = 0;
   return (int)left;
  }

bool LoadIndicators()
  {
   if(CopyBuffer(g_hEMAFast, 0, 0, 4, g_emaFast) != 4) return false;
   if(CopyBuffer(g_hEMAMid,  0, 0, 4, g_emaMid)  != 4) return false;
   if(CopyBuffer(g_hEMASlow, 0, 0, 4, g_emaSlow) != 4) return false;
   if(CopyBuffer(g_hRSI,     0, 0, 4, g_rsi)     != 4) return false;
   if(CopyBuffer(g_hBB,      0, 0, 4, g_bbMid)   != 4) return false;   // buffer 0 = middle
   if(CopyBuffer(g_hBB,      1, 0, 4, g_bbUp)    != 4) return false;   // buffer 1 = upper
   if(CopyBuffer(g_hBB,      2, 0, 4, g_bbLow)   != 4) return false;   // buffer 2 = lower
   if(CopyBuffer(g_hATR,     0, 0, 4, g_atr)     != 4) return false;
   if(CopyRates(_Symbol, _Period, 0, 4, g_rates) != 4) return false;
   return true;
  }

bool HasPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic)
         return true;
   return false;
  }

bool SpreadOK()
  {
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   return spread <= (long)InpMaxSpreadPoints;
  }

// Money made or lost per 1.0 price move per 1.0 lot. The broker's own calculation first;
// tick value only if that fails.
double MoneyPerPricePerLot(ENUM_ORDER_TYPE type, double price)
  {
   double profit = 0.0;
   double other  = (type == ORDER_TYPE_BUY) ? price + 1.0 : price - 1.0;
   if(OrderCalcProfit(type, _Symbol, 1.0, price, other, profit) && profit != 0.0)
      return MathAbs(profit);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue > 0.0 && tickSize > 0.0)
      return tickValue / tickSize;
   return 0.0;
  }

double NormalizeLots(double lots, bool roundUp)
  {
   double step = g_sym.LotsStep();
   double minL = g_sym.LotsMin();
   double maxL = g_sym.LotsMax();
   if(step <= 0.0) step = 0.01;
   double steps = lots / step;
   steps = roundUp ? MathCeil(steps - 1e-9) : MathFloor(steps + 1e-9);
   double out = steps * step;
   out = MathMax(minL, MathMin(maxL, out));
   int digits = (int)MathMax(0.0, MathCeil(-MathLog10(step)));
   return NormalizeDouble(out, digits);
  }

double StopDistance()
  {
   double point = g_sym.Point();
   double dist  = g_atr[1] * InpATRMultiplier;
   dist = MathMax(dist, InpMinSLPoints * point);
   dist = MathMin(dist, InpMaxSLPoints * point);
   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   dist = MathMax(dist, (double)(stopsLevel + 1) * point);
   return dist;
  }

// $ to risk on the next trade: the fixed minimum, or a % of the balance if that is larger,
// so profits grow the trade size (compounding) when InpRiskPercentOfBalance > 0.
double RiskDollars()
  {
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(InpUseRiskLadder && InpLadderStepBalance > 0.0)
     {
      int level = (int)MathFloor(bal / InpLadderStepBalance);
      if(level > InpLadderSteps)
         return InpLadderTopRisk;                                   // past the last step
      return MathMax(InpMinDollarRiskPerTrade, MathMax(1, level) * InpLadderRiskPerStep);
     }
   double pct = bal * InpRiskPercentOfBalance / 100.0;
   return MathMax(InpMinDollarRiskPerTrade, pct);
  }

// Lots so that hitting the stop loses AT LEAST RiskDollars() (rounded up).
double LotsForRisk(ENUM_ORDER_TYPE type, double price, double slDist)
  {
   double perLot = MoneyPerPricePerLot(type, price) * slDist;
   if(perLot <= 0.0) return 0.0;
   return NormalizeLots(RiskDollars() / perLot, true);
  }

// Shrinks the lot until the margin fits inside the allowed share of free margin.
double FitToMargin(ENUM_ORDER_TYPE type, double price, double lots)
  {
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE) * InpMaxMarginShare;
   double step = g_sym.LotsStep();
   double minL = g_sym.LotsMin();
   if(step <= 0.0) step = 0.01;
   while(lots >= minL - 1e-9)
     {
      double margin = 0.0;
      if(!OrderCalcMargin(type, _Symbol, lots, price, margin)) return 0.0;
      if(margin <= freeMargin) return lots;
      lots = NormalizeLots(lots - step, false);
      if(lots <= minL + 1e-9)
        {
         if(OrderCalcMargin(type, _Symbol, minL, price, margin) && margin <= freeMargin) return minL;
         return 0.0;
        }
     }
   return 0.0;
  }

// Closed-trade profit for this EA since `from`, from the deal history.
double RealizedSince(datetime from)
  {
   double sum = 0.0;
   if(!HistorySelect(from, TimeCurrent() + 60)) return 0.0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT && entry != DEAL_ENTRY_OUT_BY) continue;
      sum += HistoryDealGetDouble(ticket, DEAL_PROFIT)
           + HistoryDealGetDouble(ticket, DEAL_SWAP)
           + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
     }
   return sum;
  }

double FloatingPnL()
  {
   double sum = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic)
         sum += g_pos.Profit() + g_pos.Swap();
   return sum;
  }

datetime DayStart()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
  }

double TodayPnL()    { return RealizedSince(DayStart()) + FloatingPnL(); }
double Rolling7Days(){ return RealizedSince(TimeCurrent() - 7 * 86400) + FloatingPnL(); }

bool DailyLimitHit()  { return TodayPnL() <= -InpMaxDailyLossUSD; }
bool WeeklyGoalPause(){ return InpPauseAtWeeklyTarget && Rolling7Days() >= InpWeeklyProfitTarget; }

//============================== Order entry ===============================
bool OpenTrade(ENUM_ORDER_TYPE type, string reason)
  {
   if(!g_sym.RefreshRates()) return false;
   if(!SpreadOK())
     {
      g_lastAction = "skipped " + reason + ": spread too wide";
      return false;
     }
   bool   isBuy  = (type == ORDER_TYPE_BUY);
   double price  = isBuy ? g_sym.Ask() : g_sym.Bid();
   double slDist = StopDistance();
   double sl     = g_sym.NormalizePrice(isBuy ? price - slDist : price + slDist);
   double tp     = g_sym.NormalizePrice(isBuy ? price + slDist * InpRiskRewardRatio
                                               : price - slDist * InpRiskRewardRatio);
   double lots = LotsForRisk(type, price, slDist);
   if(lots <= 0.0)
     {
      g_lastAction = "skipped " + reason + ": could not size the trade";
      return false;
     }
   lots = FitToMargin(type, price, lots);
   if(lots <= 0.0)
     {
      g_lastAction = "skipped " + reason + ": not enough free margin even for the minimum lot";
      return false;
     }

   bool ok = isBuy ? g_trade.Buy(lots, _Symbol, price, sl, tp, "SAP " + reason)
                   : g_trade.Sell(lots, _Symbol, price, sl, tp, "SAP " + reason);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED))
     {
      g_lastAction = StringFormat("%s refused: %u %s", reason, rc, g_trade.ResultRetcodeDescription());
      Print("SmallAccountPro: ", g_lastAction);
      return false;
     }
   double risk = MoneyPerPricePerLot(type, price) * slDist * lots;
   g_lastAction = StringFormat("%s %s %.2f lots @ %s, risking $%.2f",
                               reason, isBuy ? "BUY" : "SELL", lots,
                               DoubleToString(price, g_sym.Digits()), risk);
   Print("SmallAccountPro: ", g_lastAction);
   return true;
  }

// The one trade right after start-up: EMA21 vs EMA50 sets the side, RSI must be moving that way.
void TryInitialTrade()
  {
   if(HasPosition())
     {
      g_initialTradeDone = true;
      return;
     }
   bool up   = g_emaFast[0] > g_emaMid[0] && g_rsi[0] > g_rsi[1];
   bool down = g_emaFast[0] < g_emaMid[0] && g_rsi[0] < g_rsi[1];
   if(!up && !down)
     {
      g_lastAction = "initial trade: waiting for EMA and RSI to agree";
      return;
     }
   if(OpenTrade(up ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, "initial"))
      g_initialTradeDone = true;
  }

void ScanForSetup()
  {
   if(HasPosition()) return;
   double atr   = g_atr[1];
   double close = g_rates[1].close;
   double near  = atr * InpTouchATR;
   double low12  = MathMin(g_rates[1].low,  g_rates[2].low);
   double high12 = MathMax(g_rates[1].high, g_rates[2].high);

   bool bullSlope = (g_emaFast[1] - g_emaFast[2]) > atr * InpSlopeATR;
   bool bearSlope = (g_emaFast[2] - g_emaFast[1]) > atr * InpSlopeATR;

   bool bullRegime = g_emaFast[1] > g_emaMid[1] && (close > g_emaSlow[1] || bullSlope);
   bool bearRegime = g_emaFast[1] < g_emaMid[1] && (close < g_emaSlow[1] || bearSlope);

   bool bullPullback = (low12 <= g_emaFast[1] + near || low12 <= g_bbMid[1] + near)
                       && low12 >= g_bbLow[1] - near && close > g_emaFast[1];
   bool bearPullback = (high12 >= g_emaFast[1] - near || high12 >= g_bbMid[1] - near)
                       && high12 <= g_bbUp[1] + near && close < g_emaFast[1];

   bool bullRSI = g_rsi[1] >= InpBuyRSIMin  && g_rsi[1] <= InpBuyRSIMax  && g_rsi[1] > g_rsi[2];
   bool bearRSI = g_rsi[1] >= InpSellRSIMin && g_rsi[1] <= InpSellRSIMax && g_rsi[1] < g_rsi[2];

   if(bullRegime && bullPullback && bullRSI)
      OpenTrade(ORDER_TYPE_BUY, "pullback");
   else if(bearRegime && bearPullback && bearRSI)
      OpenTrade(ORDER_TYPE_SELL, "pullback");
  }

//============================ Trade management ============================
void ManagePositions()
  {
   if(!g_sym.RefreshRates()) return;
   double point  = g_sym.Point();
   long   stopsL = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long   freezeL = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double minGap = (double)MathMax(stopsL, freezeL) * point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol || g_pos.Magic() != InpMagic) continue;

      bool   isBuy  = (g_pos.PositionType() == POSITION_TYPE_BUY);
      double open   = g_pos.PriceOpen();
      double sl     = g_pos.StopLoss();
      double tp     = g_pos.TakeProfit();
      double vol    = g_pos.Volume();
      double profit = g_pos.Profit() + g_pos.Swap();
      double price  = isBuy ? g_sym.Bid() : g_sym.Ask();
      double perPrice = MoneyPerPricePerLot(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, open) * vol;
      if(perPrice <= 0.0) continue;

      double newSl = sl;
      if(profit >= InpBreakEvenTriggerUSD)
        {
         double lockPx = isBuy ? open + InpBreakEvenLockUSD / perPrice
                               : open - InpBreakEvenLockUSD / perPrice;
         if(isBuy ? (lockPx > newSl || newSl == 0.0) : (lockPx < newSl || newSl == 0.0)) newSl = lockPx;
        }
      if(profit >= InpTrailStartUSD)
        {
         double trailPx = isBuy ? price - InpTrailStepUSD / perPrice
                                : price + InpTrailStepUSD / perPrice;
         if(isBuy ? (trailPx > newSl || newSl == 0.0) : (trailPx < newSl || newSl == 0.0)) newSl = trailPx;
        }
      newSl = g_sym.NormalizePrice(newSl);
      if(newSl == sl) continue;
      if(isBuy  && price - newSl < minGap) continue;   // too close to price for the broker
      if(!isBuy && newSl - price < minGap) continue;
      if(MathAbs(newSl - sl) < point) continue;
      if(g_trade.PositionModify(g_pos.Ticket(), newSl, tp))
         g_lastAction = StringFormat("moved stop to %s (profit $%.2f)", DoubleToString(newSl, g_sym.Digits()), profit);
     }
  }

//================================== HUD ===================================
void UpdateHUD()
  {
   string status;
   if(!WarmUpOver())
      status = StringFormat("WARM-UP COUNTDOWN: %ds remaining", WarmUpRemaining());
   else if(DailyLimitHit())
      status = "DAILY LOSS LIMIT HIT - no new trades until tomorrow";
   else if(WeeklyGoalPause())
      status = "WEEKLY GOAL REACHED - paused";
   else
      status = "ACTIVE SCANNING";

   string nextLots = "n/a";
   if(LoadIndicators() && g_sym.RefreshRates())
     {
      double slDist = StopDistance();
      double lots   = LotsForRisk(ORDER_TYPE_BUY, g_sym.Ask(), slDist);
      double fitted = FitToMargin(ORDER_TYPE_BUY, g_sym.Ask(), lots);
      double risk   = MoneyPerPricePerLot(ORDER_TYPE_BUY, g_sym.Ask()) * slDist * fitted;
      nextLots = fitted > 0.0 ? StringFormat("%.2f lots (stop %d pts, risks $%.2f)", fitted,
                                             (int)MathRound(slDist / g_sym.Point()), risk)
                              : "too little margin for the minimum lot";
     }

   double today = TodayPnL();
   double week  = Rolling7Days();
   Comment(StringFormat(
      "SmallAccountPro  |  %s\n"
      "Balance: $%.2f   Equity: $%.2f   Free margin: $%.2f\n"
      "Next trade size: %s   [%s]\n"
      "Today: %+.2f   (daily loss limit -%.2f)\n"
      "Rolling 7 days: %+.2f  /  weekly goal %.2f  (%.0f%%)\n"
      "Spread: %d pts (max %d)%s\n"
      "Last: %s",
      status,
      g_acc.Balance(), g_acc.Equity(), g_acc.FreeMargin(),
      nextLots,
      InpUseRiskLadder ? StringFormat("ladder: risking $%.2f at this balance", RiskDollars())
      : InpRiskPercentOfBalance > 0.0 ? StringFormat("compounding: %.2f%% of balance, min $%.2f",
                                                     InpRiskPercentOfBalance, InpMinDollarRiskPerTrade)
                                      : StringFormat("fixed $%.2f risk", InpMinDollarRiskPerTrade),
      today, InpMaxDailyLossUSD,
      week, InpWeeklyProfitTarget, InpWeeklyProfitTarget > 0 ? 100.0 * week / InpWeeklyProfitTarget : 0.0,
      (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD), InpMaxSpreadPoints,
      _Period == PERIOD_M15 ? "" : "   !! tested on M15 only - this chart is " + EnumToString(_Period),
      g_lastAction));
  }

//=============================== Lifecycle ================================
int OnInit()
  {
   if(!g_sym.Name(_Symbol))
     {
      Print("SmallAccountPro: symbol not available");
      return INIT_FAILED;
     }
   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints((ulong)InpSlippagePoints);
   if(!g_trade.SetTypeFillingBySymbol(_Symbol))
      Print("SmallAccountPro: could not read the symbol's filling mode, using the default");

   g_hEMAFast = iMA(_Symbol, _Period, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   g_hEMAMid  = iMA(_Symbol, _Period, InpEMAMid,  0, MODE_EMA, PRICE_CLOSE);
   g_hEMASlow = iMA(_Symbol, _Period, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);
   g_hRSI     = iRSI(_Symbol, _Period, InpRSIPeriod, PRICE_CLOSE);
   g_hBB      = iBands(_Symbol, _Period, InpBBPeriod, 0, InpBBDeviation, PRICE_CLOSE);
   g_hATR     = iATR(_Symbol, _Period, InpATRPeriod);
   if(g_hEMAFast == INVALID_HANDLE || g_hEMAMid == INVALID_HANDLE || g_hEMASlow == INVALID_HANDLE ||
      g_hRSI == INVALID_HANDLE || g_hBB == INVALID_HANDLE || g_hATR == INVALID_HANDLE)
     {
      Print("SmallAccountPro: could not create an indicator handle");
      return INIT_FAILED;
     }

   ArraySetAsSeries(g_emaFast, true);
   ArraySetAsSeries(g_emaMid,  true);
   ArraySetAsSeries(g_emaSlow, true);
   ArraySetAsSeries(g_rsi,     true);
   ArraySetAsSeries(g_bbUp,    true);
   ArraySetAsSeries(g_bbMid,   true);
   ArraySetAsSeries(g_bbLow,   true);
   ArraySetAsSeries(g_atr,     true);
   ArraySetAsSeries(g_rates,   true);

   if(_Period != PERIOD_M15)
      PrintFormat("SmallAccountPro WARNING: tested on M15 only. On real 2026 gold the same rules lost "
                  "95%% of $1,000 on M1 and 12%% on M5 (ea/sap_replay.py). This chart is %s.",
                  EnumToString(_Period));
   g_startTime        = TimeCurrent();
   g_initialTradeDone = !InpTradeImmediatelyAfterDelay;
   if(!EventSetTimer(1))
      Print("SmallAccountPro: timer unavailable - the HUD will update on ticks only");
   UpdateHUD();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_hEMAFast != INVALID_HANDLE) IndicatorRelease(g_hEMAFast);
   if(g_hEMAMid  != INVALID_HANDLE) IndicatorRelease(g_hEMAMid);
   if(g_hEMASlow != INVALID_HANDLE) IndicatorRelease(g_hEMASlow);
   if(g_hRSI     != INVALID_HANDLE) IndicatorRelease(g_hRSI);
   if(g_hBB      != INVALID_HANDLE) IndicatorRelease(g_hBB);
   if(g_hATR     != INVALID_HANDLE) IndicatorRelease(g_hATR);
   Comment("");
  }

void OnTimer()
  {
   UpdateHUD();
  }

void OnTick()
  {
   ManagePositions();
   if(!WarmUpOver()) UpdateHUD();
   if(!WarmUpOver()) return;
   if(!LoadIndicators()) return;
   if(DailyLimitHit() || WeeklyGoalPause()) return;

   if(!g_initialTradeDone)
     {
      TryInitialTrade();
      return;
     }

   // The setup is judged on the last CLOSED bar, so check once per new bar.
   datetime barTime = g_rates[0].time;
   if(barTime == g_lastBarTime) return;
   g_lastBarTime = barTime;
   ScanForSetup();
  }
//+------------------------------------------------------------------+
