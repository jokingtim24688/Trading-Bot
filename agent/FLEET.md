# Fleet launcher

Starts one ML bot per symbol, watches them in a terminal dashboard, and takes its
orders from Telegram.

```
python -m agent.fleet --scan                 # what's tradeable right now, and why
python -m agent.fleet                        # paper-trade every trained symbol
python -m agent.fleet --symbols XAUUSD,EURUSD
python -m agent.fleet --live                 # real orders (demo unless --allow-real)
```

## Which symbols it trades

Only ones with a trained model in `models/`. A model exists only after `agent.train`
has validated it, so the fleet can't quietly start trading something untested.
`--scan` shows each symbol's spread against its typical M1 range and refuses anything
where the spread is over 25% of that range - the cost study in `ea/frequency_study.py`
is why that limit exists.

Each bot is its own `agent.run` process, so one crashing or stalling can't take the
others with it. A bot that dies while the fleet is running is restarted automatically.

## Several agents on one symbol

```
python -m agent.fleet --symbols XAUUSD --agents 3
```

Three agents trade gold side by side. Each gets:

- **its own magic number** (261000, 261001, ...) - MT5 keeps their positions separate, and each
  agent only ever sees and manages its own. One can be long while another is short.
- **its own entry threshold** (0.50 / 0.55 / 0.60 for three) - this is the point. Identical
  agents read the same candles with the same model and take the same trade, which is just one
  agent at 3x size paying 3x the spread. Different thresholds make them disagree: the low one
  trades more often on weaker signals, the high one waits.
- **its own ledger rows** (`agent` and `magic` columns), so win rate and P/L are tracked per
  agent and you can see which threshold actually earns its keep.

### This needs a HEDGING account

Yours is one ("Demo Account - **Hedge**" in the MT5 title bar). On a **netting** account MT5
merges everything on a symbol into a single net position, so a second agent's sell would close
the first agent's buy - they would silently cancel each other out. `agent.run` prints a warning
if it detects netting with a custom magic, and the fleet says so when starting more than one.

### What still is shared, honestly

Separate positions do not mean separate risk. These agents are not independent traders:

| Shared | Why it matters |
|---|---|
| **Margin** | All agents draw on the same free margin. Enough of them open at once and the next order is refused - or worse, a margin call closes positions you did not choose. |
| **Account equity** | A drawdown is a drawdown. Per-agent limits do not add up to an account-level limit. |
| **The market** | Agents on the same symbol with similar models tend to agree. When they do, you are not diversified - you have one position at 3x size, with 3x the spread paid to get it. |

So more agents on one symbol **concentrates** risk unless they genuinely disagree, which is why
the thresholds are spread apart. Real diversification comes from different *symbols*, not more
copies on the same one. Start with `--agents 1` on several symbols before stacking agents on gold.

## Telegram commands

Link it once in the app (Settings > Phone alerts: BotFather token, then "Find my chat"),
then control the fleet from your phone:

| command | what it does |
|---|---|
| `/stop` | Stops every bot so **no new trade can open**, then waits for the open ones to reach their own stop or target. Messages you when the last one closes. |
| `/start` | Starts the bots again (also cancels a drain in progress). |
| `/pause` | Same drain as `/stop`, but ends in `paused` rather than `stopped`. |
| `/status` | State, how many bots are up, and every trade still open. |
| `/bots` | Each symbol and whether its bot is running. |
| `/total` `/prof` `/loss` | Money from the ledger (already built into `app/telegram.py`). |

Only the chat ID saved in settings is answered, so nobody else can stop your bots.

## Stopping is a drain, not a cut-off

`/stop` ends the bot processes immediately - that is what guarantees no new trade opens -
but **open trades are never force-closed**. They keep the stop and target already placed
at the broker and are left to finish on their own. The fleet sits in `draining` until the
last one closes, syncing the ledger as it goes so the results are still recorded with no
bot running, then reports itself `stopped`.

To close open trades immediately instead, use MT5 directly or the app's
Hold-to-flatten button. The fleet deliberately won't do it for you: closing at market
mid-move is a decision worth making on purpose.

## The terminal

The dashboard is read-only - symbols, whether each bot is alive, open trades, closed
trades, win rate and realised P/L straight from the ledger (not the bots' own claims).
Per-bot logs are in `logs/fleet/<symbol>.log`. Ctrl+C stops everything.
