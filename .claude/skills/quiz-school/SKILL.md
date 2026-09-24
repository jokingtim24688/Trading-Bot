---
name: quiz-school
description: How to run, read and un-stick the Trading Bot's Quiz school - the reinforcement-learning agent that answers "what do you do here?" on real gold charts where professional setups worked, with points as its only reward. Use this whenever the user mentions the Quiz tab, quiz questions, the mastery board, stuck or unclear questions, "work on picked", the quiz exam, the quiz agent's second opinion, or wants the quiz to learn more, faster or from more data.
---

# Quiz school

The quiz trains a small neural network (`agent/quiz.py`) with reinforcement learning. Each question is a real
XAUUSD M1 moment from the downloaded history:
- **Buy/sell questions:** a professional setup appeared (liquidity sweep, opening-range breakout, session-average
  reclaim, fair value gap, prior-day level test) and a pro-style trade reached 2R cleanly. That means within 3 hours,
  without first going more than 60% of the way to its stop.
- **Stay-out questions:** neither side would have been a clean trade.

The agent sees 227 inputs: 49 indicator readings plus the chart itself (the last 40 candles and a 90-candle outline).
Its only goal is points:

| Answer | Points |
|---|---|
| Right | +10 |
| Wrong way | -10 |
| Traded when it should stay out | -5 |
| Stayed out on a good trade | -3 |

A question is **finished** once it is answered right 5 times in a row. Practice is 75% of the questions; the other 25%
are an **exam** it never trains on.

## Running it (Quiz tab)
1. Train tab: **Download history**. More years means more questions (4 years is about 5,000 clean questions;
   10,000 needs most of 2009+).
2. Quiz tab: pick a size, then **Build quiz**. Rebuild after an app update that changes the inputs.
3. Start the quiz:
   - **Start over:** a fresh agent.
   - **Continue:** the saved agent and progress, saved every 20 seconds.
   - **Work on picked:** only the squares you picked on the board. Finished ones can't be picked.
4. Speed: **Max** is the default. Slower speeds exist only for watching.

On the board, each square is one practice question:

| Square | Meaning |
|---|---|
| Dark | Not right yet |
| Gold shades | On a streak |
| Solid gold | Finished |
| Grey | Stuck (it is looping on it) |
| Baby blue | The question it is on right now |
| Red outline | Its latest mistake |
| White outline | Picked |

The chart panel holds the latest mistake with the pro answer.

## It loops until done
It never quits on its own. It stops only when every question in play is finished or the user presses Stop. When no
new question is finished for 100 rounds, it escalates:
1. Asks the stuck questions 7 extra times a round with 3x bigger learning steps.
2. Doubles its network, up to 64 -> 128 -> 256 -> 512 units, keeping everything learned.
3. Resets its expectations on the stuck questions, so a right answer there is a big reward, and tries other answers
   half the time. Then it loops again.

## When questions stay stuck
Work through these in order:
1. **Let it loop.** Growth steps take a few hundred rounds. The note under the points says which tactic it is on.
2. **Pick them and use Work on picked.** It spends every answer on them.
3. **Rebuild the quiz after downloading more history.** A stuck question usually looks, to the agent, like other
   questions with the opposite answer. More examples of each setup, and the chart inputs, separate them. Builds
   already drop questions whose near-twin, or 4 of 5 closest look-alikes, has the other answer.
4. **Check the exam, not just the board.** 100% finished with a low exam score means it memorised the answers. The fix
   is a bigger quiz from more history, not longer training.

## Reading results
- The `quiz-lessons` skill is rewritten by the quiz after every run. It covers finished/stuck per setup, exam accuracy
  per setup, and which setups to trust. Read it before answering "how is the quiz doing?"
- The exam percentage is the honest number. Guessing gets about 33%.
- Settings has a **Second opinion from the quiz agent** option. With it on, the bot only enters when the quiz agent
  picks the same side. Recommend it only when the exam is well above guessing on the setups the bot trades.
- **What would you do now?** shows the agent the live MT5 chart. Treat its answer as one opinion: after mastering the
  quiz it is often very confident.

## Command line
```
python -m agent.quiz build --questions 5000
python -m agent.quiz train                   # fresh; loops until everything is finished (Stop from the app)
python -m agent.quiz train --resume          # continue the saved agent
python -m agent.quiz train --focus 46,120,733
python -m agent.quiz train --max-rounds 500  # cap, for tests
```

## Files
| File | What it holds |
|---|---|
| `data/quiz.json` | The questions |
| `data/quiz_x.npy` | Indicator inputs |
| `data/quiz_bars.npy`, `data/quiz_times.npy` | The charts |
| `data/quiz_progress.npz` | Streaks and finished flags |
| `models/quiz_policy.json` | The agent |
| `data/quiz_state.json` | Live progress for the app |
| `data/quiz_control.json` | Speed and Stop |
