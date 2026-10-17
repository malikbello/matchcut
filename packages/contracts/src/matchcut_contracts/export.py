"""Write JSON Schema files for every contract.

Usage: python -m matchcut_contracts.export [out_dir] [--check]
With --check, exit 1 if the committed schemas differ from the models (used in CI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from matchcut_contracts.models import (
    SCHEMA_VERSION,
    Club,
    MatchEvent,
    MatchMeta,
    Player,
    TrackingFrame,
    TruthRecord,
)

MODELS = {
    "club": Club,
    "player": Player,
    "match-meta": MatchMeta,
    "match-event": MatchEvent,
    "tracking-frame": TrackingFrame,
    "truth-record": TruthRecord,
}

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "schemas"


def render(name: str) -> str:
    schema = MODELS[name].model_json_schema()
    schema["$id"] = f"https://matchcut.dev/schemas/{SCHEMA_VERSION}/{name}.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    args = [a for a in argv if not a.startswith("--")]
    out = Path(args[0]) if args else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    drift = []
    for name in MODELS:
        path = out / f"{name}.schema.json"
        text = render(name)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                drift.append(path.name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
    if drift:
        print("Schemas out of date:", ", ".join(drift), "- run python -m matchcut_contracts.export")
        return 1
    print(("Schemas up to date" if check else f"Wrote {len(MODELS)} schemas") + f" in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
