//+------------------------------------------------------------------+
//| SymbolScout.mq5                                                  |
//| Ranks symbols for a candle-based day-trading EA on YOUR broker.  |
//|                                                                  |
//| Nobody can know which stock will be the most profitable. What   |
//| can be measured is where a short-term EA has the most room:      |
//|   - Room:  average candle range (ATR) vs the spread you pay.     |
//|            Low room = the spread eats the edge.                  |
//|   - Trend: how cleanly price travels each day (efficiency ratio, |
//|            0 = pure chop, 1 = straight line).                    |
//|   - Moves: average daily range as a % of price.                  |
//| Score = room x (0.5 + trend), so cheap, clean movers rank first. |
//| Then run CandleSense in the Strategy Tester on the top 3-5 and   |
//| keep the one that tests best: that's the real answer.           |
//|                                                                  |
//| Run it on any chart (Navigator > Scripts). Results: the Experts  |
//| log, the chart, and MQL5\Files\SymbolScout.csv.                  |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.00"
#property script_show_inputs

input bool            MarketWatchOnly = true;       // Only symbols in Market Watch (false = every symbol, slow)
input string          PathFilter      = "";         // Only symbols whose path contains this (e.g. "Stock", "NAS")
input ENUM_TIMEFRAMES TF              = PERIOD_M5;  // Candles to measure
input int             Days            = 10;         // How many trading days back
input int             ShowTop         = 15;         // Rows shown on the chart

struct Row
  {
   string sym;
   double room, trend, movePct, spreadPts, score;
   int    bars;
  };

bool Measure(const string sym, Row &row)
  {
   int perDay = (int)(86400 / PeriodSeconds(TF));
   int want = perDay * (Days + 2);
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = -1;
   for(int tries = 0; tries < 5 && n < 100; tries++)          // history may need a moment to download
     {
      n = CopyRates(sym, TF, 1, want, r);
      if(n < 100)
         Sleep(300);
     }
   if(n < 100)
      return false;

   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(point <= 0)
      return false;
   // average true range and median spread over the bars
   double trSum = 0;
   int trN = 0;
   double spreads[];
   ArrayResize(spreads, n);
   for(int i = 1; i < n; i++)
     {
      double tr = MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      if(tr > 0)
        {
         trSum += tr;
         trN++;
        }
      spreads[i] = (double)r[i].spread;
     }
   spreads[0] = (double)r[0].spread;
   ArraySort(spreads);
   double medSpread = spreads[n / 2] * point;
   if(medSpread <= 0)
      medSpread = SymbolInfoInteger(sym, SYMBOL_SPREAD) * point;
   if(trN == 0 || medSpread <= 0)
      return false;
   double atr = trSum / trN;

   // per day: efficiency ratio and range
   double erSum = 0, rangePctSum = 0;
   int days = 0;
   int i = 0;
   while(i < n)
     {
      MqlDateTime d0;
      TimeToStruct(r[i].time, d0);
      int j = i;
      double hi = r[i].high, lo = r[i].low, path = 0;
      while(j + 1 < n)
        {
         MqlDateTime d1;
         TimeToStruct(r[j + 1].time, d1);
         if(d1.day_of_year != d0.day_of_year || d1.year != d0.year)
            break;
         j++;
         path += MathAbs(r[j].close - r[j - 1].close);
         hi = MathMax(hi, r[j].high);
         lo = MathMin(lo, r[j].low);
        }
      if(j - i >= 12 && path > 0 && r[i].open > 0)                 // skip stub days
        {
         erSum += MathAbs(r[j].close - r[i].open) / path;
         rangePctSum += (hi - lo) / r[i].open * 100.0;
         days++;
        }
      i = j + 1;
     }
   if(days == 0)
      return false;

   row.sym = sym;
   row.room = atr / medSpread;
   row.trend = erSum / days;
   row.movePct = rangePctSum / days;
   row.spreadPts = medSpread / point;
   row.bars = n;
   row.score = row.room * (0.5 + row.trend);
   return true;
  }

void OnStart()
  {
   int total = SymbolsTotal(MarketWatchOnly);
   Row rows[];
   int count = 0;
   PrintFormat("SymbolScout: measuring %d symbols on %s, %d days...", total, EnumToString(TF), Days);
   for(int s = 0; s < total && !IsStopped(); s++)
     {
      string sym = SymbolName(s, MarketWatchOnly);
      if(PathFilter != "" && StringFind(SymbolInfoString(sym, SYMBOL_PATH), PathFilter) < 0 && StringFind(sym, PathFilter) < 0)
         continue;
      if(SymbolInfoInteger(sym, SYMBOL_TRADE_MODE) == SYMBOL_TRADE_MODE_DISABLED)
         continue;
      if(!MarketWatchOnly)
         SymbolSelect(sym, true);
      ArrayResize(rows, count + 1);
      if(!Measure(sym, rows[count]))
        {
         PrintFormat("  %s: not enough history, skipped", sym);
         continue;
        }
      count++;
     }
   if(count == 0)
     {
      Print("SymbolScout: nothing measured. Add symbols to Market Watch, open their charts once so history loads, run again.");
      return;
     }
   // sort by score, best first (an index, so no struct copies)
   int idx[];
   ArrayResize(idx, count);
   for(int a = 0; a < count; a++)
      idx[a] = a;
   for(int a = 0; a < count - 1; a++)
      for(int b = a + 1; b < count; b++)
         if(rows[idx[b]].score > rows[idx[a]].score)
           {
            int t = idx[a];
            idx[a] = idx[b];
            idx[b] = t;
           }

   int fh = FileOpen("SymbolScout.csv", FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh != INVALID_HANDLE)
      FileWrite(fh, "rank", "symbol", "score", "room_atr_per_spread", "trend_0_to_1", "daily_range_pct", "median_spread_points", "bars");
   string out = StringFormat("SymbolScout (%s, %d days): best first\n#  symbol        score   room  trend  day-range  spread\n",
                             EnumToString(TF), Days);
   Print("rank symbol score room trend dayRange% spreadPts");
   for(int k = 0; k < count; k++)
     {
      int w = idx[k];
      string line = StringFormat("%-2d %-12s %6.1f %6.1f  %4.2f   %5.2f%%   %6.0f", k + 1, rows[w].sym, rows[w].score,
                                 rows[w].room, rows[w].trend, rows[w].movePct, rows[w].spreadPts);
      Print(line);
      if(k < ShowTop)
         out += line + "\n";
      if(fh != INVALID_HANDLE)
         FileWrite(fh, k + 1, rows[w].sym, DoubleToString(rows[w].score, 2), DoubleToString(rows[w].room, 2),
                   DoubleToString(rows[w].trend, 3), DoubleToString(rows[w].movePct, 2), DoubleToString(rows[w].spreadPts, 0),
                   rows[w].bars);
     }
   if(fh != INVALID_HANDLE)
      FileClose(fh);
   out += "\nroom = candle range / spread (higher = cheaper to trade)\ntrend = 0 chop .. 1 straight line\n"
          "Next: Strategy Tester -> CandleSense on the top 3-5, keep the best.\nSaved to MQL5\\Files\\SymbolScout.csv";
   Comment(out);
   PrintFormat("SymbolScout: done, %d ranked. Top pick by this measure: %s. Confirm it in the Strategy Tester.", count, rows[idx[0]].sym);
  }
//+------------------------------------------------------------------+
