# Hermes setup (memory + "do anything" assistant)

The app's **Hermes** tab can use one of two brains. Pick one, or set up both: with the backend on
**Auto**, the app uses Hermes Agent when it's running and the local model otherwise.

| | Local Hermes model | Hermes Agent (recommended) |
|---|---|---|
| What it is | A small model (Llama 3.2 3B) running in Ollama on your CPU, so it uses no VRAM | Nous Research's open-source agent app, running in WSL |
| Memory | App memory in one plain file, `data/hermes_memory.json` (facts + chat history) | Hermes' own persistent memory + searchable past sessions, plus the app's chat log |
| Can do | MT5 account/positions/market summaries, position sizing, start/stop agent, notes, web pages, maths, memory | Everything on the left via the MT5 bridge, **plus placing trades**, web search, terminal, files, scheduled jobs, skills it writes itself, and Telegram/Discord messaging |
| Cost | Free, offline | Free app; you pick the model (local Ollama or a paid API) |
| Setup time | 5 minutes | 20–30 minutes |

---

## Option A: Local model (sets itself up)
1. Install **Ollama for Windows** from ollama.com (or press **Set up** on the Hermes tab to install it with winget).
2. That's it. When the app opens it starts Ollama and downloads `llama3.2:3b` (about 2 GB, once).
3. The model runs on the **CPU only** (Settings: `ollama_cpu_only`), so it never uses the RTX 4060's VRAM.
4. It loads when you send a message and unloads right after each reply (`ollama_keep_alive` = 0) and when you leave
   the Hermes tab. Memory stays in `data/hermes_memory.json`, so it remembers everything next time.

Replies take a few seconds each, since the model loads from disk every time. If you used `hermes3:8b` before, you can
free its 4.7 GB of disk with `ollama rm hermes3:8b`.

## Option B: Hermes Agent (full agent with memory)
Hermes Agent runs on Linux, so on Windows it lives in **WSL2** (native Windows support is experimental).
MT5 stays on Windows, and the app runs a small bridge (MCP server) so Hermes can reach it.

1. **WSL2 with mirrored networking** (so `localhost` works in both directions). In PowerShell (admin): `wsl --install`,
   reboot, then create `%USERPROFILE%\.wslconfig` containing:
   ```
   [wsl2]
   networkingMode=mirrored
   ```
   Run `wsl --shutdown` once so it takes effect.
2. **Install Hermes Agent inside WSL** using the one-line installer from the official README:
   https://github.com/NousResearch/hermes-agent. The setup wizard asks which model provider to use:
   - Free/local: point it at Ollama's OpenAI-compatible endpoint `http://localhost:11434/v1` with model `hermes3:8b`
     (Ollama from Option A, running on Windows).
   - Or any hosted provider it lists (OpenRouter, Anthropic, etc.) for a stronger model.
3. **Turn on its API server** (this is what the app talks to). Add to `~/.hermes/.env` in WSL:
   ```
   API_SERVER_ENABLED=true
   API_SERVER_KEY=pick-a-long-random-string
   ```
   then start it with `hermes gateway`. It listens on `http://127.0.0.1:8642`.
4. **Give it the MT5 tools**: merge `hermes/config.snippet.yaml` into `~/.hermes/config.yaml`, then restart
   `hermes gateway`. The app starts the bridge on Windows (`http://localhost:8765/mcp`) when it opens.
5. **Give it the trading knowledge**: copy the skill folder into Hermes' skills directory. Hermes uses the same
   `SKILL.md` format:
   `cp -r /mnt/c/<path-to>/Trading-Bot/.claude/skills/mt5-trading ~/.hermes/skills/`
   and the bot's own lessons (it rewrites these as it learns, so a symlink keeps Hermes up to date):
   `ln -s /mnt/c/<path-to>/Trading-Bot/.claude/skills/m1-bot-lessons ~/.hermes/skills/m1-bot-lessons`
6. In the app: **Settings → Hermes**, set Backend *Auto* or *Hermes Agent*, paste the API key, and save.
7. Seed its memory: open the Hermes tab and paste the contents of `hermes/user_seed.md` with "remember all of this".

### Safety with Hermes Agent
- The MT5 bridge **refuses real-money accounts** unless you set `MT5_MCP_ALLOW_REAL=1`, and rejects any order that
  risks more than 1% (`MT5_MCP_MAX_RISK_PCT`). Every order must carry a stop loss.
- Hermes Agent can run terminal commands. Keep its approval prompts on for commands.

## Does this run from disk instead of RAM?
Programs have to be in memory while they run. What this setup keeps on disk:
- Memory, chat history, notes, settings, trade journal, M1 history and trained models (`data/`, `logs/`, `models/`).
- The chat model (about 2 GB) runs on the CPU, only while it's answering, then unloads. It never uses VRAM.
- The app (~150–250 MB) and the agent (~300–500 MB with 5,000 M1 bars) are the only things in RAM.
  The top bar shows live RAM and VRAM use.
