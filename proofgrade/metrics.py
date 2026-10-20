"""Read anonymous pilot aggregates locally; no public analytics endpoint."""

import argparse
import json
from pathlib import Path
import sqlite3


def summarize(path, mode="openai"):
    path = Path(path)
    if not path.is_file():
        raise ValueError("No pilot database found. Enable opt-in collection and record attempts first.")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT rowid,* FROM attempts WHERE provider_mode=? ORDER BY rowid", (mode,)).fetchall()
    finally:
        connection.close()
    initial = [row for row in rows if row["previous_attempt_id"] is None and row["hint_status"] == "verified"]
    first_revisions = {}
    for row in rows:
        if row["previous_attempt_id"]:
            first_revisions.setdefault(row["previous_attempt_id"], row)
    corrected = sum(bool(first_revisions[row["id"]]["corrected_previous_step"])
                    for row in initial if row["id"] in first_revisions)
    revised = sum(row["id"] in first_revisions for row in initial)
    ratings = [row["rating"] for row in rows if row["rating"] is not None]
    accepted = sum(row["hint_status"] == "verified" for row in rows)
    rejected = sum(row["rejected_candidates"] for row in rows)
    return {"provider_mode": mode, "stored_attempts": len(rows), "initial_verified_hints": len(initial),
            "initial_attempts_revised": revised, "corrected_after_first_hint": corrected,
            "correction_rate": corrected / len(initial) if initial else None,
            "verified_hints": accepted,
            "withheld_hints": sum(row["hint_status"] in ("manual_review", "unavailable") for row in rows),
            "generation_calls": sum(row["generation_attempts"] for row in rows),
            "rejected_candidates": rejected,
            "candidate_validation_pass_rate": accepted / (accepted + rejected) if accepted + rejected else None,
            "rated_attempts": len(ratings), "usefulness_4_or_5_rate": sum(value >= 4 for value in ratings) / len(ratings) if ratings else None,
            "note": "Attempt-level data only. Missing revisions count as not corrected; participant survey results are separate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/proofgrade.sqlite3")
    parser.add_argument("--mode", choices=["demo", "openai", "disabled"], default="openai")
    args = parser.parse_args()
    try:
        print(json.dumps(summarize(args.db, args.mode), indent=2))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
