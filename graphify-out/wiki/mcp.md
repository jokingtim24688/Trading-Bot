# MT5 MCP bridge (`mcp_server/mt5_mcp.py`)
FastMCP (mcp 1.x; pinned `<2` because 2.x renamed FastMCP). Transports: stdio (Claude Desktop/Code) or `--http` streamable HTTP at `http://127.0.0.1:8765/mcp` (Hermes Agent in WSL).
Tools: `mt5_account_info`, `mt5_search_symbols`, `mt5_symbol_spec`, `mt5_get_tick`, `mt5_get_m1_bars`, `mt5_list_positions`, `mt5_position_size` (read-only); `mt5_place_order`, `mt5_modify_position`, `mt5_close_position` (destructive).
Guards: real accounts refused unless `MT5_MCP_ALLOW_REAL=1`; SL required and on the correct side; risk ≤ `MT5_MCP_MAX_RISK_PCT` (1%); magic 260924.
