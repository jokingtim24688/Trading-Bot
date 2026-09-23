# MT5 MCP Server

Lets Claude (Desktop or Code, on the Windows trading PC) read M1 data and manage trades in a running MT5 terminal.

## Install
```powershell
pip install -r requirements.txt   # includes mcp and MetaTrader5
```

## Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "mt5": {
      "command": "C:\\path\\to\\Trading-Bot\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Trading-Bot\\mcp_server\\mt5_mcp.py"],
      "env": { "MT5_MCP_MAX_RISK_PCT": "1.0" }
    }
  }
}
```
## Claude Code
`claude mcp add mt5 -- C:\path\to\.venv\Scripts\python.exe C:\path\to\Trading-Bot\mcp_server\mt5_mcp.py`

## Tools
| Tool | Kind |
|---|---|
| `mt5_account_info`, `mt5_search_symbols`, `mt5_symbol_spec`, `mt5_get_tick`, `mt5_get_m1_bars`, `mt5_list_positions`, `mt5_position_size` | read-only |
| `mt5_place_order`, `mt5_modify_position`, `mt5_close_position` | trading |

## Safety settings (environment variables)
| Var | Default | Effect |
|---|---|---|
| `MT5_MCP_ALLOW_REAL` | unset | Trading tools refuse real-money accounts unless `1` |
| `MT5_MCP_MAX_RISK_PCT` | `1.0` | Rejects orders whose SL risk exceeds this % of equity |
| `MT5_MCP_MAGIC` | `260924` | Magic number on Claude-placed orders |
| `MT5_TERMINAL_PATH` | unset | Specific `terminal64.exe` to attach to |

Every order must include a stop loss. Algo Trading must be enabled in the terminal (Ctrl+E).
