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
