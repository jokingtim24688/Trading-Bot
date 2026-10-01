//+------------------------------------------------------------------+
//| CandleSenseICT.mq5                                               |
//| An advanced, single-file Smart-Money / ICT Expert Advisor for    |
//| XAUUSD (gold) on MetaTrader 5.                                   |
//|                                                                  |
//| Combines, in one EA:                                             |
//|  - Fair Value Gap (FVG) detection with a 0-100 quality score      |
//|    (gap size, displacement strength, HTF trend alignment,         |
//|    freshness, premium/discount) - adapted from the MIT-licensed   |
//|    open-source FvgGold-EA (github.com/foeed/FvgGold-EA).          |
//|  - Order Block (OB) detection; an FVG that overlaps a fresh OB    |
//|    gets a confluence bonus, same idea as FvgGold-EA.              |
//|  - Liquidity sweep detection (stop-hunt wick beyond a recent      |
//|    high/low that closes back inside) - the idea CandleSense.mq5   |
//|    already used, kept here as its own confluence signal.          |
//|  - H1 EMA 50/200 trend bias filter, only trading with the trend.  |
//|  - ICT killzones: London open, NY open, London/NY overlap (GMT),  |
//|    trading paused outside them.                                   |
//|  - Risk-based position sizing through OrderCalcProfit() (not the  |
//|    tick value), so the lot size is correct on every broker.       |
//|  - ATR stop loss, fixed R:R or ATR-multiple target, break-even    |
//|    and ATR trailing once a trade is in profit.                    |
//|  - A daily loss limit, a max-trades-per-day cap and a spread      |
//|    filter.                                                        |
//|  - Self-learning: each setup type (FVG only, FVG+OB confluence,   |
//|    FVG+liquidity sweep, all three) is weighted by its own closed  |
//|    trade history, persisted across restarts (global variables),   |
//|    and a type that keeps losing needs a higher score to trade     |
//|    again - the same "learn from itself" idea as CandleSense.mq5.  |
//|                                                                    |
//| Test it in the Strategy Tester and on a DEMO account first.       |
//| Nothing here guarantees profit.                                   |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.01"
#property description "ICT-style FVG + Order Block + liquidity sweep EA for gold, with killzone/trend filters, correct risk-based sizing and self-learning setup weights."
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//================================= Inputs ==================================
input group "=== Setup timeframe & lookback ==="
input ENUM_TIMEFRAMES SetupTF        = PERIOD_M15; // Timeframe FVGs/OBs are found on
input ENUM_TIMEFRAMES TrendTF        = PERIOD_H1;  // Timeframe for the EMA trend bias
input int    LookbackBars            = 150;        // Bars scanned for FVGs/OBs each check

input group "=== Fair Value Gap ==="
input double MinGapPoints            = 25;         // Minimum FVG size, points
input int    MinAgeBars              = 1;          // FVG must be at least this many bars old
input int    MaxAgeBars              = 20;         // FVG expires after this many bars unfilled
input double FVGBuffer               = 30;         // Entry buffer into the gap, points

input group "=== Order Block ==="
input double OB_MinSizePoints        = 10;         // Minimum OB candle size, points
input int    OB_LookbackBars         = 50;         // Bars scanned for order blocks
input double OB_MaxDistancePoints    = 200;        // Max distance for FVG/OB confluence, points
input double OB_ConfluenceBonus      = 20;         // Score bonus when FVG sits on a fresh OB

input group "=== Liquidity sweep ==="
input int    SweepLookback           = 20;         // Bars scanned for the swept high/low
input double SweepMinPoints          = 15;         // Minimum wick-beyond-level size, points
input double SweepBonus              = 15;         // Score bonus when a sweep backs the FVG

input group "=== Scoring & trend filter ==="
input double MinScore                = 55.0;       // Minimum 0-100 score to take a trade
input int    EMA_Fast                = 50;          // HTF fast EMA
input int    EMA_Slow                = 200;         // HTF slow EMA
input bool   RequireTrendAlign       = true;        // Only trade with the H1 EMA50/200 bias

input group "=== Killzones (broker/GMT offset below) ==="
input int    GMT_Offset_Hours        = 0;           // Broker server time minus GMT (check your broker)
input bool   UseKillzones            = true;        // Restrict entries to ICT killzones
input int    KZ_LondonStart          = 7;           // London open killzone start, GMT
input int    KZ_LondonEnd            = 10;          // London open killzone end, GMT
input int    KZ_OverlapStart         = 12;          // London/NY overlap start, GMT
input int    KZ_NYEnd                = 16;          // NY killzone end, GMT

input group "=== Stops, target, sizing ==="
input int    ATR_Period              = 14;          // ATR period (setup timeframe)
input double ATR_SL_Mult             = 1.0;         // Stop = ATR x this, beyond the FVG/OB edge
input bool   UseFixedRR              = true;        // true = fixed R:R target, false = ATR target
input double RiskRewardRatio         = 2.0;         // Target distance = stop distance x this
input double ATR_TP_Mult             = 3.0;         // Used only when UseFixedRR = false
input double RiskPercent             = 0.5;         // % of balance risked per trade

input group "=== Break-even & trailing ==="
input bool   UseBreakEven            = true;        // Move stop to entry once in profit
input double BE_TriggerR             = 1.0;         // Move to BE once profit reaches this x risk
input double BE_LockPoints           = 20;          // Points of profit locked in at BE
input bool   UseTrailing             = true;        // ATR trailing stop after break-even
input double Trail_ATR_Mult          = 1.5;         // Trail distance = ATR x this

input group "=== Account protection ==="
input double DailyLossLimitPct       = 3.0;         // Stop trading for the day after this % balance loss
input int    MaxTradesPerDay         = 6;           // New entries allowed per day
input int    MaxOpenTrades           = 2;           // Open trades allowed at once
input double MaxSpreadPoints         = 40;          // Refuse entries when spread exceeds this
input int    MagicNumber             = 260930;      // Order magic number

input group "=== Self-learning ==="
input bool   UseLearning             = true;        // Down-weight setup types that keep losing
input int    LearnMinSamples         = 6;           // Trades needed before a type's weight moves
input double LearnMaxPenalty         = 25.0;        // Max score penalty for a weak setup type

//================================= State ====================================
enum SetupKind { SETUP_FVG_ONLY = 0, SETUP_FVG_OB = 1, SETUP_FVG_SWEEP = 2, SETUP_FVG_OB_SWEEP = 3, SETUP_COUNT = 4 };
string g_setupName[SETUP_COUNT] = {"FVG only", "FVG+OrderBlock", "FVG+Sweep", "FVG+OB+Sweep"};

struct FVGZone
  {
   double top, bottom;
   int    type;        // 1 bullish, -1 bearish
   int    barIndex;    // bar the gap formed on (0 = current forming bar excluded)
   bool   traded;
  };

struct OBZone
  {
   double top, bottom;
   int    type;
   int    barIndex;
  };

double   g_dayStartEquity = 0;
datetime g_dayStamp        = 0;
int      g_tradesToday     = 0;
int      g_lastTradedBar   = -1;

input group "=== HUD ==="
input bool   ShowHUD                 = true;         // Show the on-chart Trades/Earned/Lost/Subtotal panel

int    g_hudTrades = 0;
double g_hudEarned = 0, g_hudLost = 0;
#define HUD_PREFIX "CSICT_HUD_"

int g_hATR_setup = INVALID_HANDLE;
int g_hEMA_fast_setup = INVALID_HANDLE;
int g_hEMA_fast_trend = INVALID_HANDLE;
int g_hEMA_slow_trend = INVALID_HANDLE;

// Forward declarations (used before their definitions further down this file).
bool FVGHasOBConfluence(double gapTop, double gapBot, int type, double point);
bool SweepSupports(int fvgType);

//============================ Learning weights ==============================
// Persisted per setup kind: wins, losses, total R. Global variables survive restarts.
string LW_Key(SetupKind k, string field) { return "CSICT_" + Symbol() + "_" + (string)k + "_" + field; }

void Learn_Load(SetupKind k, double &wins, double &losses, double &totalR)
  {
   wins   = GlobalVariableCheck(LW_Key(k,"w"))  ? GlobalVariableGet(LW_Key(k,"w"))  : 0;
   losses = GlobalVariableCheck(LW_Key(k,"l"))  ? GlobalVariableGet(LW_Key(k,"l"))  : 0;
   totalR = GlobalVariableCheck(LW_Key(k,"r"))  ? GlobalVariableGet(LW_Key(k,"r"))  : 0;
  }

void Learn_Record(SetupKind k, double rMultiple)
  {
   double wins, losses, totalR;
   Learn_Load(k, wins, losses, totalR);
   if(rMultiple > 0) wins += 1; else losses += 1;
   totalR += rMultiple;
   GlobalVariableSet(LW_Key(k,"w"), wins);
   GlobalVariableSet(LW_Key(k,"l"), losses);
   GlobalVariableSet(LW_Key(k,"r"), totalR);
  }

// Returns a score penalty 0..LearnMaxPenalty for a setup type with a losing track record.
double Learn_Penalty(SetupKind k)
  {
   if(!UseLearning) return 0;
   double wins, losses, totalR;
   Learn_Load(k, wins, losses, totalR);
   double n = wins + losses;
   if(n < LearnMinSamples) return 0;
   double avgR = totalR / n;
   if(avgR >= 0) return 0;
   // Scale: avgR of -1.0 (losing a full stop on average) => full penalty.
   double frac = MathMin(1.0, -avgR / 1.0);
   return frac * LearnMaxPenalty;
  }

//================================= HUD panel ===================================
// Same minimal style as CandleSense.mq5 v1.40: just Trades / Earned / Lost / Subtotal.
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
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_XSIZE, 150);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_YSIZE, 78);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_BGCOLOR, clrBlack);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_BACK, false);
   ObjectSetInteger(0, HUD_PREFIX+"bg", OBJPROP_SELECTABLE, false);
   HUD_Label("title", 16, 24, "CandleSenseICT", clrGold);
   HUD_Update();
  }

void HUD_Update()
  {
   if(!ShowHUD) return;
   double subtotal = g_hudEarned + g_hudLost;
   HUD_Label("trades",   16, 42, StringFormat("Trades: %d", g_hudTrades), clrWhite);
   HUD_Label("earned",   16, 58, StringFormat("Earned: %.2f", g_hudEarned), clrLimeGreen);
   HUD_Label("lost",     16, 74, StringFormat("Lost: %.2f", g_hudLost), clrTomato);
   HUD_Label("subtotal", 16, 90, StringFormat("Subtotal: %.2f", subtotal), subtotal >= 0 ? clrLimeGreen : clrTomato);
  }

void HUD_Remove()
  {
   ObjectsDeleteAll(0, HUD_PREFIX);
  }

//================================= Helpers ===================================
double Pt() { return SymbolInfoDouble(_Symbol, SYMBOL_POINT); }

// Indicator handles are created once (OnInit) and reused; creating a fresh handle on every
// call (as a first draft of this EA did) leaks handles and eventually returns INVALID_HANDLE.
double ATR(int period, int shift=1)
  {
   if(g_hATR_setup == INVALID_HANDLE) return 0;
   double buf[];
   if(CopyBuffer(g_hATR_setup, 0, shift, 1, buf) <= 0) return 0;
   return buf[0];
  }

double EMA(ENUM_TIMEFRAMES tf, int period, int shift=1)
  {
   int h = (tf == SetupTF) ? g_hEMA_fast_setup : (period == EMA_Fast ? g_hEMA_fast_trend : g_hEMA_slow_trend);
   if(h == INVALID_HANDLE) return 0;
   double buf[];
   if(CopyBuffer(h, 0, shift, 1, buf) <= 0) return 0;
   return buf[0];
  }

// 1 = bullish bias, -1 = bearish, 0 = no clear bias
int HTFBias()
  {
   double fast = EMA(TrendTF, EMA_Fast);
   double slow = EMA(TrendTF, EMA_Slow);
   if(fast == 0 || slow == 0) return 0;
   if(fast > slow) return 1;
   if(fast < slow) return -1;
   return 0;
  }

bool IsKillzoneActive()
  {
   if(!UseKillzones) return true;
   datetime gmt = TimeCurrent() - GMT_Offset_Hours * 3600;
   MqlDateTime dt; TimeToStruct(gmt, dt);
   int h = dt.hour;
   bool london  = (h >= KZ_LondonStart  && h < KZ_LondonEnd);
   bool nyBlock = (h >= KZ_OverlapStart && h < KZ_NYEnd);
   return london || nyBlock;
  }

void CheckNewDay()
  {
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", dt.year, dt.mon, dt.day));
   if(today != g_dayStamp)
     {
      g_dayStamp = today;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_BALANCE);
      g_tradesToday = 0;
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

//=========================== FVG detection ===================================
// Scans closed bars [2 .. LookbackBars] on SetupTF for a 3-candle Fair Value Gap,
// scores it, and returns the best untraded zone still within range of price.
bool FindBestFVG(FVGZone &best, double &score, SetupKind &kind, int htfBias)
  {
   double atrSetup = ATR(ATR_Period, 1);
   if(atrSetup <= 0) return false;
   double point = Pt();
   bool found = false;
   double bestScore = -1;

   for(int i = 2; i < MathMin(LookbackBars, iBars(_Symbol, SetupTF) - 4); i++)
     {
      double h1 = iHigh(_Symbol, SetupTF, i);     // most recent of the 3 (closest to i-2... see below)
      double l1 = iLow(_Symbol, SetupTF, i);
      double h3 = iHigh(_Symbol, SetupTF, i + 2);
      double l3 = iLow(_Symbol, SetupTF, i + 2);
      // middle candle i+1 is the impulse candle whose body drives displacement
      double o2 = iOpen(_Symbol, SetupTF, i + 1);
      double c2 = iClose(_Symbol, SetupTF, i + 1);
      double h2 = iHigh(_Symbol, SetupTF, i + 1);
      double l2 = iLow(_Symbol, SetupTF, i + 1);

      int type = 0; double gapTop = 0, gapBot = 0;
      if(l3 > h1) { gapTop = l3; gapBot = h1; type = 1; }          // bullish FVG
      else if(h3 < l1) { gapTop = l1; gapBot = h3; type = -1; }    // bearish FVG

      if(type == 0) continue;
      double gapSize = (gapTop - gapBot) / point;
      if(gapSize < MinGapPoints) continue;

      int ageBars = i; // bars since the gap's near edge formed
      if(ageBars < MinAgeBars || ageBars > MaxAgeBars) continue;

      // Still unfilled? price must not have fully traded back through the gap since.
      bool filled = false;
      for(int j = 1; j < i; j++)
        {
         double hj = iHigh(_Symbol, SetupTF, j), lj = iLow(_Symbol, SetupTF, j);
         if(type == 1 && lj <= gapBot) { filled = true; break; }
         if(type == -1 && hj >= gapTop) { filled = true; break; }
        }
      if(filled) continue;

      if(RequireTrendAlign && htfBias != 0 && type != htfBias) continue;

      // --- Score ---
      double score0 = 0;
      score0 += MathMin(gapSize / (atrSetup / point), 1.0) * 30.0;                       // gap size, 0-30
      double range2 = (h2 - l2); double body2 = MathAbs(c2 - o2);
      double disp = (range2 > 0) ? body2 / range2 : 0;
      score0 += disp * 30.0;                                                              // displacement, 0-30
      if(htfBias != 0 && type == htfBias) score0 += 20.0;                                 // HTF align, 0-20
      double freshness = 1.0 - (double)ageBars / MaxAgeBars;
      score0 += MathMax(0, freshness) * 10.0;                                             // freshness, 0-10
      double emaS = EMA(SetupTF, EMA_Fast, i);
      if(emaS > 0)
        {
         if(type == 1 && gapTop < emaS) score0 += 10.0;   // discount for a buy
         if(type == -1 && gapBot > emaS) score0 += 10.0;  // premium for a sell
        }

      SetupKind k = SETUP_FVG_ONLY;
      bool obHit = FVGHasOBConfluence(gapTop, gapBot, type, point);
      bool sweepHit = SweepSupports(type);
      if(obHit)    score0 += OB_ConfluenceBonus;
      if(sweepHit) score0 += SweepBonus;
      if(obHit && sweepHit) k = SETUP_FVG_OB_SWEEP;
      else if(obHit)        k = SETUP_FVG_OB;
      else if(sweepHit)     k = SETUP_FVG_SWEEP;

      score0 -= Learn_Penalty(k);
      score0 = MathMax(0, MathMin(100, score0));

      if(score0 > bestScore)
        {
         bestScore = score0;
         best.top = gapTop; best.bottom = gapBot; best.type = type; best.barIndex = i; best.traded = false;
         kind = k;
         found = true;
        }
     }
   score = bestScore;
   return found;
  }

//=========================== Order Block detection ===========================
bool FVGHasOBConfluence(double gapTop, double gapBot, int type, double point)
  {
   double atrSetup = ATR(ATR_Period, 1);
   if(atrSetup <= 0) return false;
   for(int i = 1; i < MathMin(OB_LookbackBars, iBars(_Symbol, SetupTF) - 3); i++)
     {
      double o1 = iOpen(_Symbol, SetupTF, i),   c1 = iClose(_Symbol, SetupTF, i);
      double o2 = iOpen(_Symbol, SetupTF, i+1), c2 = iClose(_Symbol, SetupTF, i+1);
      int obType = 0; double obTop = 0, obBot = 0;
      if(c2 < o2 && c1 > o1 && MathAbs(c1 - o1) >= atrSetup * 1.5) { obType = 1; obTop = MathMax(o2,c2); obBot = MathMin(o2,c2); }
      else if(c2 > o2 && c1 < o1 && MathAbs(c1 - o1) >= atrSetup * 1.5) { obType = -1; obTop = MathMax(o2,c2); obBot = MathMin(o2,c2); }
      if(obType == 0 || obType != type) continue;
      double obSize = (obTop - obBot) / point;
      if(obSize < OB_MinSizePoints) continue;
      // overlap or close enough
      bool overlap = !(obTop < gapBot || obBot > gapTop);
      double dist = overlap ? 0 : MathMin(MathAbs(obTop - gapBot), MathAbs(gapTop - obBot)) / point;
      if(overlap || dist <= OB_MaxDistancePoints) return true;
     }
   return false;
  }

//=========================== Liquidity sweep ==================================
// A sweep: a bar's wick pokes beyond the recent swing high/low and closes back inside it.
// type 1 (bullish FVG) wants a sweep of recent lows; type -1 wants a sweep of recent highs.
bool SweepSupports(int fvgType)
  {
   double point = Pt();
   double swingHigh = -1, swingLow = 1e9;
   for(int i = 3; i < SweepLookback + 3; i++)
     {
      swingHigh = MathMax(swingHigh, iHigh(_Symbol, SetupTF, i));
      swingLow  = MathMin(swingLow,  iLow(_Symbol, SetupTF, i));
     }
   for(int i = 0; i < 3; i++)
     {
      double h = iHigh(_Symbol, SetupTF, i), l = iLow(_Symbol, SetupTF, i), c = iClose(_Symbol, SetupTF, i);
      if(fvgType == 1 && l < swingLow - SweepMinPoints*point && c > swingLow) return true;
      if(fvgType == -1 && h > swingHigh + SweepMinPoints*point && c < swingHigh) return true;
     }
   return false;
  }

//================================ Sizing ======================================
// Risk-based lot size using OrderCalcProfit, so the real per-lot loss on THIS
// broker/symbol is used instead of a generic tick value (the fix CandleSense
// v1.50 made to its own sizing bug).
double LotsForRisk(double riskMoney, double entry, double stop, bool isBuy)
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
   double lots = riskMoney / lossPerTestLot * testLot;

   lots = MathFloor(lots / step) * step;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return NormalizeDouble(lots, 2);
  }

//================================== Entries ===================================
void TryEnter()
  {
   if(CountMyOpenTrades() >= MaxOpenTrades) return;
   if(g_tradesToday >= MaxTradesPerDay) return;
   if(DailyLimitHit()) return;
   if(UseKillzones && !IsKillzoneActive()) return;

   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID)) / Pt();
   if(spread > MaxSpreadPoints) return;

   int bias = HTFBias();
   FVGZone zone; double score; SetupKind kind;
   if(!FindBestFVG(zone, score, kind, bias)) return;
   if(score < MinScore) return;
   if(zone.barIndex == g_lastTradedBar) return; // don't re-fire on the same just-formed gap bar

   double point = Pt();
   double atrSetup = ATR(ATR_Period, 1);
   bool isBuy = (zone.type == 1);
   double entry = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);

   double edge = isBuy ? zone.bottom : zone.top;
   double sl = isBuy ? edge - atrSetup * ATR_SL_Mult - FVGBuffer*point
                     : edge + atrSetup * ATR_SL_Mult + FVGBuffer*point;
   double slDist = MathAbs(entry - sl);
   if(slDist <= 0) return;

   double tp;
   if(UseFixedRR) tp = isBuy ? entry + slDist * RiskRewardRatio : entry - slDist * RiskRewardRatio;
   else           tp = isBuy ? entry + atrSetup * ATR_TP_Mult   : entry - atrSetup * ATR_TP_Mult;

   double stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   if(MathAbs(entry - sl) < stopsLevel || MathAbs(entry - tp) < stopsLevel) return;

   double riskMoney = AccountInfoDouble(ACCOUNT_BALANCE) * RiskPercent / 100.0;
   double lots = LotsForRisk(riskMoney, entry, sl, isBuy);
   if(lots <= 0) return;

   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = isBuy ? trade.Buy(lots, _Symbol, entry, sl, tp, "CS-ICT " + g_setupName[kind])
                   : trade.Sell(lots, _Symbol, entry, sl, tp, "CS-ICT " + g_setupName[kind]);
   if(ok)
     {
      g_tradesToday++;
      g_lastTradedBar = zone.barIndex;
      GlobalVariableSet("CSICT_" + Symbol() + "_lastkind_" + (string)trade.ResultOrder(), (double)kind);
      PrintFormat("CandleSenseICT: %s %.2f lots @ %.2f sl %.2f tp %.2f score %.1f setup %s",
                  isBuy?"BUY":"SELL", lots, entry, sl, tp, score, g_setupName[kind]);
     }
  }

//============================ Trade management =================================
void ManageOpenTrades()
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber || PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      bool isBuy   = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double point = Pt();
      double riskDist = MathAbs(entry - sl);
      if(riskDist <= 0) continue;
      double profitR = isBuy ? (price - entry) / riskDist : (entry - price) / riskDist;

      double newSl = sl;
      if(UseBreakEven && profitR >= BE_TriggerR)
        {
         double beSl = isBuy ? entry + BE_LockPoints*point : entry - BE_LockPoints*point;
         if((isBuy && beSl > sl) || (!isBuy && beSl < sl)) newSl = beSl;
        }
      if(UseTrailing && profitR >= BE_TriggerR)
        {
         double atrSetup = ATR(ATR_Period, 1);
         double trailSl = isBuy ? price - atrSetup*Trail_ATR_Mult : price + atrSetup*Trail_ATR_Mult;
         if((isBuy && trailSl > newSl) || (!isBuy && trailSl < newSl)) newSl = trailSl;
        }
      if(newSl != sl)
         trade.PositionModify(ticket, newSl, tp);
     }
  }

//=========================== Learn from closed deals ============================
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   ulong posId = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) + HistoryDealGetDouble(trans.deal, DEAL_SWAP) + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   double volume = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);

   g_hudTrades++;
   if(profit >= 0) g_hudEarned += profit; else g_hudLost += profit;
   HUD_Update();

   if(!UseLearning) return;
   double openPrice = 0, slAtOpen = 0;
   // Look back through history for the opening deal of this position to recover the original risk.
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong d = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(d, DEAL_POSITION_ID) != posId) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN)
        {
         openPrice = HistoryDealGetDouble(d, DEAL_PRICE);
         break;
        }
     }
   if(openPrice <= 0 || volume <= 0) return;

   string kindKey = "CSICT_" + Symbol() + "_lastkind_" + (string)posId;
   SetupKind kind = SETUP_FVG_ONLY;
   if(GlobalVariableCheck(kindKey)) kind = (SetupKind)(int)GlobalVariableGet(kindKey);

   // Approximate R using account-currency profit vs a 1-lot proxy risk is unreliable across
   // partials; use sign of profit as a simple win/loss signal, which is enough to steer weights.
   double rApprox = (profit > 0) ? 1.0 : (profit < 0 ? -1.0 : 0.0);
   Learn_Record(kind, rApprox);
  }

//================================== Lifecycle ====================================
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   g_dayStamp = 0;
   CheckNewDay();

   g_hATR_setup      = iATR(_Symbol, SetupTF, ATR_Period);
   g_hEMA_fast_setup = iMA(_Symbol, SetupTF, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   g_hEMA_fast_trend = iMA(_Symbol, TrendTF, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   g_hEMA_slow_trend = iMA(_Symbol, TrendTF, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   if(g_hATR_setup == INVALID_HANDLE || g_hEMA_fast_setup == INVALID_HANDLE ||
      g_hEMA_fast_trend == INVALID_HANDLE || g_hEMA_slow_trend == INVALID_HANDLE)
     {
      Print("CandleSenseICT: failed to create an indicator handle - check symbol/timeframe.");
      return INIT_FAILED;
     }

   HUD_Create();
   PrintFormat("CandleSenseICT v1.00 loaded on %s %s. Killzones %s, learning %s.",
               _Symbol, EnumToString(SetupTF), UseKillzones?"on":"off", UseLearning?"on":"off");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_hATR_setup != INVALID_HANDLE)      IndicatorRelease(g_hATR_setup);
   if(g_hEMA_fast_setup != INVALID_HANDLE) IndicatorRelease(g_hEMA_fast_setup);
   if(g_hEMA_fast_trend != INVALID_HANDLE) IndicatorRelease(g_hEMA_fast_trend);
   if(g_hEMA_slow_trend != INVALID_HANDLE) IndicatorRelease(g_hEMA_slow_trend);
   HUD_Remove();
  }

void OnTick()
  {
   CheckNewDay();
   ManageOpenTrades();

   static datetime lastBarTime = 0;
   datetime curBarTime = iTime(_Symbol, SetupTF, 0);
   if(curBarTime == lastBarTime) return;
   lastBarTime = curBarTime;

   TryEnter();
  }
//+------------------------------------------------------------------+
