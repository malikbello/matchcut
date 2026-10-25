"""The Recap Factory: at the whistle, every fan's film is made at once, one job replica per film.

A run is every film a match's fans can ask for: each club, and each player with a moment of
their own, in every voiced language. The API writes the run and puts one message per film on the
`cuts` queue; KEDA starts a job replica per message, so the films are made side by side. Each
replica joins its film from the match's pieces (losslessly: the moment clips were rendered once,
during the match), mixes the soundtrack in the fan's language, has the QA agent listen to it and
read it, and records what it took and what it cost. The Factory screen reads it all back.

    factory/<match>/<aspect>/latest.json          the latest run's id
    factory/<match>/<aspect>/<run>/run.json       when it started, and its films
    factory/<match>/<aspect>/<run>/<film>.json    a film's status, timings, cost and QA verdict
    factory/<match>/<aspect>/<run>/<film>.mp4     the film
    factory/<match>/<aspect>/<run>/<film>.qa.json the QA agent's full report
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from matchcut_editing.edl import slug

# Azure list prices in eastus2, read from the Azure Retail Prices API on 23 Oct 2026
PRICES = {
    "vcpu_s": 0.000024,  # Container Apps consumption: a vCPU, active, per second
    "gib_s": 0.000003,  # a GiB of memory, active, per second
    "speech_h": 1.0,  # Speech to text (S1), per hour of audio
    "tokens_in": 0.25e-6,  # gpt-5-mini (Global), per input token
    "tokens_out": 2.0e-6,  # per output token
}
STALE_S = 900  # a film still being made after this long has lost its replica
RUN_ID = re.compile(r"^f-[0-9a-f]{12}$")
FILM_ID = re.compile(r"^(home|away|p-[a-z0-9-]+)\.[A-Za-z-]+$")


def root(match: str, aspect: str) -> str:
    return f"factory/{match}/{aspect}/"


def film_id(focus: dict[str, str], lang: str) -> str:
    """A film's name in URLs and blobs: plain ASCII, so Adé and Ade are both p-ade."""
    if focus.get("player"):
        folded = unicodedata.normalize("NFKD", focus["player"]).encode("ascii", "ignore").decode()
        return f"p-{slug(folded)}.{lang}"
    return f"{focus['side']}.{lang}"


def plan(focuses: list[dict[str, str]], langs: list[str]) -> list[dict[str, Any]]:
    """A run's films: every focus in every language, clubs first, as the screen lays them out."""
    return [{"id": film_id(f, lang), "focus": f, "lang": lang} for f in focuses for lang in langs]


def cost(replica_s: float, vcpu: float, gib: float, usage: dict[str, float]) -> dict[str, float]:
    """What a film cost at list price: the replica's time, and the QA agent's listening and reading."""
    compute = replica_s * (vcpu * PRICES["vcpu_s"] + gib * PRICES["gib_s"])
    qa = (
        usage.get("audio_s", 0) / 3600 * PRICES["speech_h"]
        + usage.get("tokens_in", 0) * PRICES["tokens_in"]
        + usage.get("tokens_out", 0) * PRICES["tokens_out"]
    )
    return {"compute": round(compute, 6), "qa": round(qa, 6), "total": round(compute + qa, 6)}


def _status(st: dict[str, Any], now: float) -> str:
    status = st.get("status", "waiting")
    if status == "making" and now - st.get("started", now) > STALE_S:
        return "failed"
    if status == "done":
        return "checked" if (st.get("qa") or {}).get("passed") else "flagged"
    return status


def run_state(run: dict[str, Any], films: dict[str, dict[str, Any]], now: float) -> dict[str, Any]:
    """The screen's view of a run: each film's state, and the run's numbers (all measured)."""
    t0 = run["started"]
    cells = []
    for f in run["films"]:
        st = films.get(f["id"], {})
        cells.append(
            {
                **f,
                "status": _status(st, now),
                "seconds": st.get("seconds"),
                "at": round(st["finished"] - t0, 1) if st.get("finished") else None,
                "duration": st.get("duration"),
                "cost": st.get("cost"),
                "qa": st.get("qa"),
            }
        )
    counts = dict.fromkeys(("waiting", "making", "checked", "flagged", "failed"), 0)
    for c in cells:
        counts[c["status"]] += 1
    made = [films[c["id"]] for c in cells if c["status"] in ("checked", "flagged")]
    # replicas at work over time: +1 when a film starts, -1 when it is made
    steps = sorted(
        [(st["started"] - t0, 1, 0) for st in films.values() if st.get("started")]
        + [(st["finished"] - t0, -1, 1) for st in films.values() if st.get("finished")]
    )
    timeline, making, done, peak = [[0.0, 0, 0]], 0, 0, 0
    for t, d_making, d_done in steps:
        making, done = making + d_making, done + d_done
        peak = max(peak, making)
        timeline.append([round(max(t, 0.0), 1), done, making])
    finished = counts["waiting"] == counts["making"] == 0
    ends = [st["finished"] for st in made]
    mean = {
        k: round(sum(st["cost"][k] for st in made) / len(made), 6) for k in ("compute", "qa", "total")
    } if made else None  # fmt: skip
    return {
        "run": run["run"],
        "started": t0,
        "finished": finished,
        "elapsed": round((max(ends) if finished and ends else now) - t0, 1),
        "films": cells,
        "counts": counts,
        "total": len(cells),
        "first_film_s": round(min(ends) - t0, 1) if ends else None,
        "all_films_s": round(max(ends) - t0, 1) if finished and ends else None,
        "peak_replicas": peak,
        "cost_per_film": mean,
        "qa_passed": f"{counts['checked']}/{len(made)}",
        "timeline": timeline,
        "pieces": run.get("pieces"),
    }
