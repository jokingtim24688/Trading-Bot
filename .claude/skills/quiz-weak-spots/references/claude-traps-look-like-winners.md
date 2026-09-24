# Traps look like winners: don't grind on them (written by Claude from the 2026-09-24 22:24 report)

## What the report showed
The report covered 73,667 questions (55,250 practice): 34,848 finished and 20,382 stuck. The exam was 69.7%.

- **Real setups are learned.**
  - Fades, trend pullbacks, Asian raids, sweeps and prior-day holds score 83–98% on the exam.
  - Opening-range breakouts score 83–85%.
  - Fair value gaps are the weakest real setups at 66–74%.
- **Traps are not.** Every trap group scores 5–36% on the exam, and the trap groups hold 9,986 of the stuck
  questions. The usual mistake is taking the setup (BUY or SELL at 76–96%).
- Trap groups score higher in practice than on the exam (e.g. 39% vs 5%). That means it memorises individual charts
  instead of learning a rule.

## What Claude tested
**Idea:** keep a trap only when most of its 5 closest look-alikes also say "stay out". In the bank, 44% of traps have
mostly *winning* look-alikes, so "stay out" there is hindsight.

**Test:** the same 12,000-question quiz, 400 rounds, the same seed, on the sandbox's 4-year stand-in history.

| | Exam | Winners | Traps | No-setup spots |
|---|---|---|---|---|
| As it is | 72.3% | 88.9% | 13.1% | 65.1% |
| Only "agreed" traps | 71.0% | 88.6% | 17.1% | 56.3% |

Even traps whose look-alikes agree stay near 17%, and the stay-out spots got worse. **The change was not kept.**

## What it means
- A trap is a setup whose stop was hit within the hour. At the moment of entry it looks like its winners; the
  failure is decided later.
- Its only weak tell is a quiet, small-candle market (see claude-traps-quiet-markets.md). The agent already sees
  that input, and it isn't enough.
- For a setup that wins about 2 out of 3 times at 2R, taking it is the right trade. The quiz scores the trap as a
  mistake, but in points the agent's "take it" is the better bet.

## How to use this
- **Don't press "Work on these" on trap groups.** It can't generalise there. It only memorises, and pushing the
  network toward STAY OUT on winner-like charts is what caused the earlier exam collapse
  (claude-exam-collapse-forgetting.md).
- **Do "Work on these" for real setups that are below 80% on the exam:** bullish and bearish fair value gaps (74% / 66%).
- **Judge the quiz agent by its exam on real setups** (not traps). Trust its second opinion on the setups at 85%+
  on the exam. Treat its BUY/SELL in a quiet market as a coin flip.
- The stuck count will stay high because of traps. That's expected. A rising exam on real setups is the number to
  watch.
- **Ideas not yet tried** (ask Claude):
  - Count trap questions as "either answer OK" when the look-alikes are split.
  - Score traps by expected points instead of right/wrong.
  - Add a "day's range so far vs normal" input.
