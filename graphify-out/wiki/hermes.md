# Hermes assistant + memory
- **brain.py**: backends `hermes_agent` (Nous Research Hermes Agent API server, `POST /v1/chat/completions`, headers `X-Hermes-Session-Id`/`X-Hermes-Session-Key`, bearer key), `local` (Ollama `/api/chat`, model `hermes3:8b`, `keep_alive` to unload VRAM, tool loop ≤ 6 rounds), `auto`.
- **memory.py**: SQLite `data/memory.db`, tables `messages`, `facts`; `relevant_facts` keyword ranking; `search_messages`.
- **tools.py** (local backend): get_account, get_positions, get_m1_market, position_size, agent_status, start_agent (paper/demo), stop_agent, remember, recall, web_fetch, save_note/list_notes/read_note (`data/notes/`), calculate (AST-safe), current_time. No order placement.
- **hermes/**: `SETUP.md` (Option A: Ollama; Option B: Hermes Agent in WSL2 with mirrored networking, API server, MCP bridge, skill copy), `config.snippet.yaml` (`mcp_servers.mt5.url`), `user_seed.md`.
- RAM vs disk: persistent state on disk; the model lives in VRAM and unloads after idle.
