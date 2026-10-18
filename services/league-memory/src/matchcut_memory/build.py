"""Build the League Memory database from the seeded universe.

python -m matchcut_memory.build --seed 2026 --out data/league/memory.sqlite
"""

from __future__ import annotations

import argparse

from matchcut_sim.universe import build_universe

from matchcut_memory.db import build_db


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="matchcut-memory-build")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/league/memory.sqlite")
    args = ap.parse_args(argv)
    path = build_db(build_universe(args.seed), args.out)
    print(f"League Memory written to {path}")


if __name__ == "__main__":
    main()
