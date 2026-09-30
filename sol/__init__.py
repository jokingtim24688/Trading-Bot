"""Solana meme-coin "trenching" bot: rug filter, ML ensemble that debates each trade, main agents with subagents.

Paper trading by default. Live trading needs SOL_PRIVATE_KEY in .env and a typed LIVE; the key never leaves this
package and no route returns it. Everything the bot writes goes under data/ (sol.db, sol_models/, quiz_bank/trenching/).
"""
