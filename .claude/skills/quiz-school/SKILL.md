---
name: quiz-school
description: How to run, read and un-stick the Trading Bot's Quiz school - the reinforcement-learning agent that answers "what do you do here?" on real gold charts where professional setups worked, with points as its only reward. Use this whenever the user mentions the Quiz tab, quiz questions, the mastery board, stuck or unclear questions, "work on picked", the quiz exam, the quiz agent's second opinion, or wants the quiz to learn more, faster or from more data.
---

# Quiz school

The quiz trains a small neural network (`agent/quiz.py`) with reinforcement learning. Each question is a real
XAUUSD M1 moment from the downloaded history, in one of three kinds:

| Kind | Share | Answer | What it is |
|---|---|---|---|
| Clean pro trade | about 65% | buy/sell | One of 18 setups appeared and a pro-style trade reached 2R cleanly: within 3 hours, without first going more than 60% of the way to its stop |
| Trap | about 15% | stay out | The setup appeared but its stop was hit within the hour. Teaches when to skip a setup |
| Stay-out spot | about 20% | stay out | Middle of the day's range, no level or setup, and neither side would have been a clean trade |

The 18 setups:
- Liquidity sweep of recent highs/lows.
- London/NY opening-range breakout.
- Session-average reclaim/loss.
- Fair value gap with the H1 trend.
- Prior-day high/low test.
- Asian range high/low raided.
- H1 trend pullback to the 20 EMA.
- Break-and-hold of the prior-day high/low.
- Fading a stretch more than 4 ATR from the session average.

How the builder picks questions:
- Cleanest, fastest examples first, spread evenly across the years.
- Round-robin over the setups.
- An hour apart, tightening to 30, then 15 minutes, only when more questions are needed.
- It drops contradictions (a near-twin, or most of the 5 closest look-alikes, has the other answer) and near-copies,
  then tops up with fresh candidates.
- Each question is graded **easy/medium/hard** by how much its look-alikes agree. Training starts with easy and medium
  and adds the hard ones once 90% of those are finished (or after 60 rounds).

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
1. Train tab: **Download history**. More years means more questions. With tightened spacing, 4 years holds roughly
   19,000; the full 2009+ history holds several times that.
2. Quiz tab: type any size from 40 to 100,000 (suggestions in the box), then **Build quiz**. If the history runs out
   of room, the build says how many it found. Rebuild after an app update that changes the builder.
3. Start the quiz:
   - **Start over:** a fresh agent.
   - **Continue:** the saved agent and progress, saved every 20 seconds.
   - **Work on picked:** only the squares you picked on the board. Finished ones can't be picked.
4. **Wipe** (next to Stop, click twice) deletes every question and its progress so you can build a fresh quiz.
   The trained agent is kept.
5. Speed: **Max** is the default. Slower speeds exist only for watching.

On the board, each square is one practice question:

| Square | Meaning |
|---|---|
| Dark | Not right yet |
| Gold shades | On a streak (squares shrink to 2 px for quizzes over 20,000) |
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
python -m agent.quiz build --questions 25000
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

## Weak spots: the automatic report and Claude's skills
Every 5 minutes while the quiz runs, and after every run, `agent/quiz_report.py` writes a weak-spot report.

Groups:
- Each setup, with traps counted separately.
- One combined "Traps (all setups)" group.

For each group it records practice and exam accuracy, finished share, stuck count, and its usual mistake. The worst
8 groups become **weak spots**. For each weak spot it:
- compares the questions it misses with the ones it gets right on readable measures: time window, weekday, year,
  volatility, H1 trend support, how far price has already travelled (session average, 200 EMA, day's range), RSI
  lean, round numbers, prior-day levels and spread;
- checks whether traps can be told apart from winners on the chart at all.

It writes three things:

| Output | What it is |
|---|---|
| `data/quiz_report.md` | The report the **Copy report for Claude** button copies |
| `data/quiz_report.json` | Feeds the Quiz tab's Weak spots panel (with a **Work on these** button per spot) |
| `.claude/skills/quiz-weak-spots/` | The auto skill, with one page per spot |

When the user pastes a report, read it and do three things:
1. Write `quiz-weak-spots/references/claude-<topic>.md` pages covering what you can work out: the likely market
   reason, what a pro would check, and whether to trust the agent there.
2. Propose builder or input changes the report points to, e.g. a filter, a new setup condition, or a new input when
   "nothing on the chart separates" the traps.
3. Tell the user which weak spots to put on the board with **Work on these**.

`claude-*` pages are never overwritten by the automatic report. Read the numbers critically: small groups (under
about 30 questions) produce chance patterns.
