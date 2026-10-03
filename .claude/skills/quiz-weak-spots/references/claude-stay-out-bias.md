# The agent now stays out of real setups (written by Claude from the 2026-10-03 03:33 report)

## What the report showed
On a fresh 73,667-question quiz (exam not taken yet):
- On every real setup, the usual mistake is **STAY OUT**, 70–96% of the time. On 2026-09-24 it was the opposite: it
  took the traps.
- The weakest real setups are the session-average setups (50%), the opening-range breakouts (57%) and the fair value
  gaps (59–62%).
- Two patterns repeat across those weak spots:
  - **RSI already leaning the trade's way.** It misses more when RSI(14) already points with the trade (e.g. 0.12 vs
    0.04 on Opening-range breakout up). This appears in all six real-setup weak spots.
  - **London morning** (10:00–12:59 server). This holds 38% of the misses on Opening-range breakout up and 31% on
    Bullish fair value gap, against 24% and 19% of the ones it gets right.

## Why: the points make "stay out" the safe answer
The quiz scores a right answer +10, a trade when it should stay out −5, and staying out of a good trade −3.
- On a chart where the agent thinks it's a winner with chance p, trading pays 10p − 5(1−p), and staying out pays
  10(1−p) − 3p.
- **Trading only wins when p > 54%.** In money, a 2R trade pays from p > 33%.
- So whenever a setup could be a trap, staying out scores better. Since traps look like winners
  (claude-traps-look-like-winners.md), most setups always could be a trap, and it backs off.
- The patterns are where that doubt is highest:
  - **RSI leaning with the trade** looks like a late entry. Traps taught it that, but in Claude's check, how far RSI
    leans changes the setups' result by only about ±0.05R a trade, which is noise.
  - **London morning** is the pre-New York stretch, where breakouts often reverse. That one is a real market habit.

## Don't "fix" it by changing the points
Making a missed winner cost more (e.g. −20) would bring the line down to 33%. But the quiz's own mix is about 61%
winners, while in the market each setup hits its 2R only about 28–31% of the time (claude-setups-without-edge.md).
An agent tuned to take setups at that mix would take far more losing trades live. For now, its caution is closer to
the money than its "mistakes" suggest.

## What to do
- Judge the agent by its exam and by the edge table ("Do the setups pay on their own?" in the report), not by how
  often it says BUY or SELL in practice.
- Don't press Work on these for the real setups with STAY OUT mistakes until the edge table shows the setup pays.
  Drilling would teach it to take setups that may lose money.
- For Opening-range breakout up and Bullish fair value gap, treat the London morning (10:00–12:59 server) as a
  no-trade window, as the report suggests.
- If the edge table shows some setups paying on your real history, Claude can make the quiz's winner share match each
  setup's real hit rate. Then the points and the market agree, and the agent's answers can be trusted as trades.
