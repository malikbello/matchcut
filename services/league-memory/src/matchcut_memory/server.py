"""League Memory MCP server (Model Context Protocol, official Python SDK v2).

Exposes only read-only, parameterised tools. Run locally over stdio:
    matchcut-memory --db data/league/memory.sqlite
or over streamable HTTP for the cloud lane:
    matchcut-memory --db data/league/memory.sqlite --http --port 8090
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from matchcut_memory.queries import LeagueMemory

mcp = MCPServer("league-memory")
_memory: LeagueMemory | None = None


def memory() -> LeagueMemory:
    global _memory  # noqa: PLW0603 - one read-only connection per process
    if _memory is None:
        _memory = LeagueMemory(os.environ.get("LEAGUE_MEMORY_DB", "data/league/memory.sqlite"))
    return _memory


@mcp.tool()
def player_profile(player_id: str) -> dict[str, Any]:
    """Career and season totals, current club and transfer history for one player (e.g. p00042)."""
    return memory().player_profile(player_id)


@mcp.tool()
def goal_context(player_id: str, is_home: bool) -> dict[str, Any]:
    """Facts that become true if this player scores now: droughts ended, milestones, first goals."""
    return memory().goal_context(player_id, is_home)


@mcp.tool()
def milestones_near(player_id: str, within: int = 3) -> dict[str, Any]:
    """Goal and appearance milestones this player is within reach of."""
    return memory().milestones_near(player_id, within)


@mcp.tool()
def head_to_head(club_a: str, club_b: str, last: int = 10) -> dict[str, Any]:
    """Recent league meetings between two clubs (club IDs like 'kes', 'irv')."""
    return memory().head_to_head(club_a, club_b, last)


@mcp.tool()
def club_form(club_id: str, last: int = 5) -> dict[str, Any]:
    """A club's recent results, unbeaten run and winless run."""
    return memory().club_form(club_id, last)


@mcp.tool()
def top_scorers(season: str | None = None, limit: int = 10) -> dict[str, Any]:
    """League top scorers for a season (e.g. '2025-26') or across all recorded seasons."""
    return memory().top_scorers(season, limit)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="matchcut-memory")
    ap.add_argument("--db", default=os.environ.get("LEAGUE_MEMORY_DB", "data/league/memory.sqlite"))
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args(argv)
    os.environ["LEAGUE_MEMORY_DB"] = args.db
    if args.http:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=args.port)  # noqa: S104 - container ingress
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
