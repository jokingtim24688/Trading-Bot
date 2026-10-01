// SmallAccountProNT v1.00 - SmallAccountPro (ea/SmallAccountPro.mq5) ported to NinjaTrader 8
// for CME 1-Ounce Gold futures (1OZ) on a 30-minute chart.
//
// Same rules as the MT5 EA, with the settings that passed ea/futures_replay.py on real gold
// (Mar-Sep 2026, $400 start, $2 round-trip commission, 1-tick spread):
//   trend    EMA21 vs EMA50, plus price above/below EMA200 or EMA21 sloping > 0.05 x ATR
//   setup    the last two candles dipped to EMA21 or the middle Bollinger band (within 0.1 x ATR),
//            stayed inside the outer band, and the candle closed back on the trend side of EMA21
//   RSI      buys 45-68 and rising, sells 32-55 and falling
//   stop     1.5 x ATR(14), kept between $5.00 and $25.00 (500-2,500 points); target 1.8 x stop
//   size     the risk ladder in $ -> contracts, rounded up; never more margin than 80% of balance
//   manage   +$2.50 open profit: stop to entry +$0.50;  from +$4.00: trail $1.50 behind the best price
//   limits   one trade at a time, stop for the day after -$15 realized, no new trades after
//            15:30 New York time, flat by 16:30 New York time (CME's daily break is 17:00)
//
// Install: copy this file to Documents\NinjaTrader 8\bin\Custom\Strategies, open
// New > NinjaScript Editor, press F5 to compile. Setup and testing steps: ninjatrader/README.md.

#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class SmallAccountProNT : Strategy
    {
        private const string SigLong = "SAP Long";
        private const string SigShort = "SAP Short";

        private EMA ema21, ema50, ema200;
        private RSI rsi;
        private Bollinger bands;
        private TimeZoneInfo newYork;

        private double dayStartProfit;
        private double entryPrice, currentStop;
        private int stopTicks, targetTicks;
        private string lastNote = "waiting for the first closed candle";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "SmallAccountProNT";
                Description = "SmallAccountPro for CME 1-Ounce Gold (1OZ), 30-minute chart.";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 1800;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 1;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Gtc;
                TraceOrders = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 200;
                IsInstantiatedOnEachOptimizationIteration = true;

                StartingBalance = 400;
                UseRiskLadder = true;
                FixedRiskDollars = 5;
                LadderStepBalance = 100;
                LadderRiskPerStep = 5;
                LadderSteps = 5;
                LadderTopRisk = 50;
                LadderBigFrom = 1500;
                LadderBigStep = 1000;
                LadderBigAdd = 50;
                MaxContracts = 50;
                DayMarginPerContract = 60;
                MaxMarginShare = 0.8;

                AtrMultiplier = 1.5;
                MinStopDollars = 5.00;
                MaxStopDollars = 25.00;
                RiskRewardRatio = 1.8;
                BreakEvenTriggerUSD = 2.5;
                BreakEvenLockUSD = 0.5;
                TrailStartUSD = 4.0;
                TrailStepUSD = 1.5;
                MaxDailyLossUSD = 15;
                NoEntriesAfter = 1530;
                FlatAt = 1630;
            }
            else if (State == State.DataLoaded)
            {
                ema21 = EMA(21);
                ema50 = EMA(50);
                ema200 = EMA(200);
                rsi = RSI(14, 3);
                bands = Bollinger(2, 20);
                newYork = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 2)
                return;
            if (Bars.IsFirstBarOfSession)
                dayStartProfit = ClosedProfit();

            DateTime ny = TimeZoneInfo.ConvertTime(Time[0], Core.Globals.GeneralOptions.TimeZoneInfo, newYork);
            int hhmm = ny.Hour * 100 + ny.Minute;

            if (Position.MarketPosition != MarketPosition.Flat)
            {
                if (hhmm >= FlatAt && hhmm < 1800)
                {
                    if (Position.MarketPosition == MarketPosition.Long)
                        ExitLong("Flat for the break", SigLong);
                    else
                        ExitShort("Flat for the break", SigShort);
                    lastNote = "closing before CME's daily break";
                }
                else
                    ManageStop();
                DrawHud();
                return;
            }

            if (CurrentBar < BarsRequiredToTrade)
                return;

            double balance = Balance();
            double dayResult = ClosedProfit() - dayStartProfit;
            if (dayResult <= -MaxDailyLossUSD)
                lastNote = string.Format("daily loss limit hit ({0:C2}) - back next session", dayResult);
            else if (hhmm >= NoEntriesAfter && hhmm < 1800)
                lastNote = "no new trades this close to the daily break";
            else
                LookForEntry(balance);
            DrawHud();
        }

        private void LookForEntry(double balance)
        {
            double a = AtrSma(14);
            double c = Close[0];
            double touch = a * 0.10, slope = a * 0.05;
            double low12 = Math.Min(Low[0], Low[1]);
            double high12 = Math.Max(High[0], High[1]);

            bool bull = ema21[0] > ema50[0] && (c > ema200[0] || ema21[0] - ema21[1] > slope);
            bool bear = ema21[0] < ema50[0] && (c < ema200[0] || ema21[1] - ema21[0] > slope);
            bull = bull && (low12 <= ema21[0] + touch || low12 <= bands.Middle[0] + touch)
                        && low12 >= bands.Lower[0] - touch && c > ema21[0];
            bear = bear && (high12 >= ema21[0] - touch || high12 >= bands.Middle[0] - touch)
                        && high12 <= bands.Upper[0] + touch && c < ema21[0];
            bull = bull && rsi[0] >= 45 && rsi[0] <= 68 && rsi[0] > rsi[1];
            bear = bear && rsi[0] >= 32 && rsi[0] <= 55 && rsi[0] < rsi[1];
            if (!bull && !bear)
            {
                lastNote = "no setup on the last candle";
                return;
            }

            double stop = Math.Min(Math.Max(a * AtrMultiplier, MinStopDollars), MaxStopDollars);
            stopTicks = Math.Max(1, (int)Math.Round(stop / TickSize));
            targetTicks = Math.Max(1, (int)Math.Round(stop * RiskRewardRatio / TickSize));
            double pointValue = Instrument.MasterInstrument.PointValue;
            double risk = RiskDollars(balance);

            int qty = Math.Max(1, (int)Math.Ceiling(risk / (stopTicks * TickSize * pointValue) - 1e-9));
            qty = Math.Min(qty, MaxContracts);
            while (qty > 1 && qty * DayMarginPerContract > balance * MaxMarginShare)
                qty--;
            if (qty * DayMarginPerContract > balance * MaxMarginShare)
            {
                lastNote = "setup skipped: not enough balance for one contract's margin";
                return;
            }

            string sig = bull ? SigLong : SigShort;
            SetStopLoss(sig, CalculationMode.Ticks, stopTicks, false);
            SetProfitTarget(sig, CalculationMode.Ticks, targetTicks);
            if (bull)
                EnterLong(qty, sig);
            else
                EnterShort(qty, sig);
            lastNote = string.Format("{0} {1} x 1OZ, stop {2:C2}, target {3:C2}, risking {4:C2}",
                bull ? "BUY" : "SELL", qty, stopTicks * TickSize, targetTicks * TickSize,
                stopTicks * TickSize * pointValue * qty);
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price,
            int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            if (execution.Order == null || execution.Order.OrderState != OrderState.Filled)
                return;
            string name = execution.Order.Name;
            if (name != SigLong && name != SigShort)
                return;
            entryPrice = execution.Order.AverageFillPrice;
            currentStop = name == SigLong ? entryPrice - stopTicks * TickSize : entryPrice + stopTicks * TickSize;
        }

        // Break-even, then trailing stop, worked out from the candle that just closed.
        private void ManageStop()
        {
            bool isLong = Position.MarketPosition == MarketPosition.Long;
            double perPoint = Instrument.MasterInstrument.PointValue * Position.Quantity;
            if (entryPrice <= 0 || perPoint <= 0)
                return;
            double best = isLong ? High[0] - entryPrice : entryPrice - Low[0];
            double newStop = currentStop;

            if (best * perPoint >= BreakEvenTriggerUSD)
            {
                double be = isLong ? entryPrice + BreakEvenLockUSD / perPoint : entryPrice - BreakEvenLockUSD / perPoint;
                newStop = isLong ? Math.Max(newStop, be) : Math.Min(newStop, be);
            }
            if (best * perPoint >= TrailStartUSD)
            {
                double trail = isLong ? High[0] - TrailStepUSD / perPoint : Low[0] + TrailStepUSD / perPoint;
                newStop = isLong ? Math.Max(newStop, trail) : Math.Min(newStop, trail);
            }
            newStop = isLong ? Math.Floor(newStop / TickSize) * TickSize : Math.Ceiling(newStop / TickSize) * TickSize;
            newStop = Instrument.MasterInstrument.RoundToTickSize(newStop);

            bool better = isLong ? newStop > currentStop : newStop < currentStop;
            bool valid = isLong ? newStop < Close[0] : newStop > Close[0];
            if (better && valid)
            {
                currentStop = newStop;
                SetStopLoss(isLong ? SigLong : SigShort, CalculationMode.Price, currentStop, false);
                lastNote = string.Format("stop moved to {0}", currentStop);
            }
        }

        // ATR as MT5's iATR works it out (simple average of the true range), like the tested replay.
        private double AtrSma(int period)
        {
            int n = Math.Min(period, CurrentBar);
            double sum = 0;
            for (int k = 0; k < n; k++)
                sum += Math.Max(High[k] - Low[k], Math.Max(Math.Abs(High[k] - Close[k + 1]), Math.Abs(Low[k] - Close[k + 1])));
            return n > 0 ? sum / n : High[0] - Low[0];
        }

        // $5 per $100 of balance up to $599, $50 from $600, then +$50 for every $1,000 past $1,500.
        private double RiskDollars(double balance)
        {
            if (!UseRiskLadder || LadderStepBalance <= 0)
                return FixedRiskDollars;
            if (LadderBigStep > 0 && balance >= LadderBigFrom)
                return LadderTopRisk + Math.Floor((balance - LadderBigFrom) / LadderBigStep) * LadderBigAdd;
            int level = (int)Math.Floor(balance / LadderStepBalance);
            if (level > LadderSteps)
                return LadderTopRisk;
            return Math.Max(FixedRiskDollars, Math.Max(1, level) * LadderRiskPerStep);
        }

        private double ClosedProfit()
        {
            return SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
        }

        private double Balance()
        {
            return StartingBalance + ClosedProfit();
        }

        private void DrawHud()
        {
            double balance = Balance();
            string text = string.Format(
                "SmallAccountProNT v1.00   ({0}-minute chart{1})\n" +
                "Balance {2:C2}   risk per trade {3:C2}   today {4:C2} (limit -{5:C2})\n" +
                "Trades {6}   won {7}   lost {8}\n" +
                "Position {9} {10}{11}\n" +
                "Last: {12}",
                BarsPeriod.Value, BarsPeriod.BarsPeriodType == BarsPeriodType.Minute && BarsPeriod.Value == 30 ? "" : " - tested on 30-minute",
                balance, RiskDollars(balance), ClosedProfit() - dayStartProfit, MaxDailyLossUSD,
                SystemPerformance.AllTrades.Count, SystemPerformance.AllTrades.WinningTrades.Count,
                SystemPerformance.AllTrades.LosingTrades.Count,
                Position.MarketPosition, Position.Quantity,
                Position.MarketPosition == MarketPosition.Flat ? "" : string.Format(" @ {0}, stop {1}", entryPrice, currentStop),
                lastNote);
            Draw.TextFixed(this, "SapHud", text, TextPosition.TopLeft);
        }

        #region Properties
        [NinjaScriptProperty, Range(1, double.MaxValue)]
        [Display(Name = "Starting balance ($)", Description = "Balance the risk ladder starts from; the strategy adds its own closed profit to it.", Order = 1, GroupName = "1. Money")]
        public double StartingBalance { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Use risk ladder", Order = 2, GroupName = "1. Money")]
        public bool UseRiskLadder { get; set; }

        [NinjaScriptProperty, Range(0.25, double.MaxValue)]
        [Display(Name = "Fixed / minimum risk per trade ($)", Order = 3, GroupName = "1. Money")]
        public double FixedRiskDollars { get; set; }

        [NinjaScriptProperty, Range(1, double.MaxValue)]
        [Display(Name = "Ladder: balance step ($)", Order = 4, GroupName = "1. Money")]
        public double LadderStepBalance { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Ladder: risk added per step ($)", Order = 5, GroupName = "1. Money")]
        public double LadderRiskPerStep { get; set; }

        [NinjaScriptProperty, Range(1, int.MaxValue)]
        [Display(Name = "Ladder: steps before top risk", Order = 6, GroupName = "1. Money")]
        public int LadderSteps { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Ladder: top risk ($)", Order = 7, GroupName = "1. Money")]
        public double LadderTopRisk { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Ladder: big steps start at ($)", Order = 8, GroupName = "1. Money")]
        public double LadderBigFrom { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Ladder: big step size ($)", Order = 9, GroupName = "1. Money")]
        public double LadderBigStep { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Ladder: risk added per big step ($)", Order = 10, GroupName = "1. Money")]
        public double LadderBigAdd { get; set; }

        [NinjaScriptProperty, Range(1, int.MaxValue)]
        [Display(Name = "Max contracts", Order = 11, GroupName = "1. Money")]
        public int MaxContracts { get; set; }

        [NinjaScriptProperty, Range(1, double.MaxValue)]
        [Display(Name = "Day margin per contract ($)", Description = "Check your broker's intraday margin for 1OZ and set it here.", Order = 12, GroupName = "1. Money")]
        public double DayMarginPerContract { get; set; }

        [NinjaScriptProperty, Range(0.05, 1.0)]
        [Display(Name = "Max share of balance used as margin", Order = 13, GroupName = "1. Money")]
        public double MaxMarginShare { get; set; }

        [NinjaScriptProperty, Range(0.1, double.MaxValue)]
        [Display(Name = "ATR multiplier for the stop", Order = 1, GroupName = "2. Stop and target")]
        public double AtrMultiplier { get; set; }

        [NinjaScriptProperty, Range(0.25, double.MaxValue)]
        [Display(Name = "Min stop ($ of price)", Order = 2, GroupName = "2. Stop and target")]
        public double MinStopDollars { get; set; }

        [NinjaScriptProperty, Range(0.25, double.MaxValue)]
        [Display(Name = "Max stop ($ of price)", Order = 3, GroupName = "2. Stop and target")]
        public double MaxStopDollars { get; set; }

        [NinjaScriptProperty, Range(0.1, double.MaxValue)]
        [Display(Name = "Target = stop x", Order = 4, GroupName = "2. Stop and target")]
        public double RiskRewardRatio { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Break-even after open profit of ($)", Order = 5, GroupName = "2. Stop and target")]
        public double BreakEvenTriggerUSD { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Break-even locks in ($)", Order = 6, GroupName = "2. Stop and target")]
        public double BreakEvenLockUSD { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Trail from open profit of ($)", Order = 7, GroupName = "2. Stop and target")]
        public double TrailStartUSD { get; set; }

        [NinjaScriptProperty, Range(0.01, double.MaxValue)]
        [Display(Name = "Trail distance ($)", Order = 8, GroupName = "2. Stop and target")]
        public double TrailStepUSD { get; set; }

        [NinjaScriptProperty, Range(0, double.MaxValue)]
        [Display(Name = "Daily loss limit ($)", Order = 1, GroupName = "3. Limits")]
        public double MaxDailyLossUSD { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "No new trades after (New York time, HHMM)", Order = 2, GroupName = "3. Limits")]
        public int NoEntriesAfter { get; set; }

        [NinjaScriptProperty, Range(0, 2359)]
        [Display(Name = "Close everything at (New York time, HHMM)", Order = 3, GroupName = "3. Limits")]
        public int FlatAt { get; set; }
        #endregion
    }
}
