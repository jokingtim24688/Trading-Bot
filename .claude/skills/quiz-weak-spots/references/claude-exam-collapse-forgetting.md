# Exam collapse = forgetting (written by Claude from the 2026-09-24 report)

## What the report showed
The quiz had 14,908 questions, 11,123 of 11,181 practice questions "finished", and an exam of **24.0%**, which is
below guessing (~33%).

| Group | Practice right | Exam (unseen) |
|---|---|---|
| Liquidity sweep above highs | 89% | **0%** (560) |
| Liquidity sweep below lows | 88% | **1%** (553) |
| No setup (stay out) | 65% | 4% (692) |
| Traps (all setups) | 48% | 1% (336) |
| Opening-range breakouts, prior-day breaks | 57–70% | 66–78% |

A model that merely failed to generalise would land near 33% on unseen sweeps, not 0%. Sweep-above-highs practice
answers are SELL in 1,637 of 1,667 cases, so any model that remembered anything would answer SELL. A score of 0%
means it now answers something else for every sweep: it **forgot**.

## Why it happened
- Finished questions used to stay gold forever, even if the agent later forgot them.
- Training that focuses on a narrow set, such as **Work on these** on a trap group whose answer is STAY OUT, pushes
  the network toward that answer for similar-looking charts, like sweeps.
- Nothing re-checked the finished ones, so the board kept saying 99.5% while the real knowledge drained away. Only
  the exam could show it.

## What changed (2026-09-24)
- **Honest finish:** a question counts as finished only when it's right 5 times in a row **and** its best answer is
  right, not 5 lucky picks.
- **Memory check** every 10 rounds and before the exam. It silently re-checks finished questions (no learning, no
  points). Any it gets wrong goes back on the board. Expect some gold squares to turn back; that's the real state.
- **Silent refresher** (Settings, on by default): each learning step also rehearses as many finished questions as
  new ones. They're never asked, shown or scored. Turning it off brings the forgetting back.
- **Exam history:** a drop of more than 5 points prints a warning, and the weak-spot report shows it at the top.

## How to use this
- Judge the agent by the **exam**, never by the board alone.
- Keep "Work on these" / "Work on picked" runs short, then press **Continue**, which runs the memory check and
  retrains what was lost.
- If the exam is below 33%, don't trust "What would you do now?" or the second-opinion filter until a Continue run
  brings it back up.
