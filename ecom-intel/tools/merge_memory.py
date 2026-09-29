#!/usr/bin/env python3
"""Merge a run's snapshot.json into the persistent memory (ecom-intel/memory/).

Usage: python3 ecom-intel/tools/merge_memory.py ecom-intel/runs/<run_id>/snapshot.json

- memory/snapshots.jsonl       one line per run (append; a re-merge of the same run_id replaces it)
- memory/problem_registry.json problems keyed by ID, with a per-run status history
- memory/decisions_log.json    decisions keyed by ID, with human approval + outcome

Problem status rules (see memory/SCHEMA.md): NEW / OLD / IMPROVING / WORSENING /
RESOLVED (absent for 2 consecutive runs) / RECURRING (seen again after RESOLVED).
The agent's own status_vs_previous is kept when it is more specific than OLD.
"""
import json
import sys
from pathlib import Path

MEM = Path(__file__).resolve().parent.parent / "memory"


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def main(snapshot_path):
    snap = json.loads(Path(snapshot_path).read_text())
    run_id = snap["run_id"]
    MEM.mkdir(exist_ok=True)

    snaps_path = MEM / "snapshots.jsonl"
    runs = [json.loads(l) for l in snaps_path.read_text().splitlines() if l.strip()] if snaps_path.exists() else []
    runs = [r for r in runs if r["run_id"] != run_id] + [snap]
    snaps_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs))

    reg_path = MEM / "problem_registry.json"
    reg = load(reg_path, {})
    seen = set()
    for p in snap.get("problems", []):
        pid = p["id"]
        seen.add(pid)
        entry = reg.get(pid)
        if entry is None:
            status = "NEW"
            entry = {"first_seen": run_id, "history": []}
        elif entry.get("current_status") == "RESOLVED":
            status = "RECURRING"
        else:
            status = p.get("status_vs_previous") if p.get("status_vs_previous") not in (None, "NEW") else "OLD"
        entry.update({k: v for k, v in p.items() if k != "status_vs_previous"})
        entry["current_status"] = status
        entry["last_seen"] = run_id
        entry["history"] = [h for h in entry["history"] if h["run_id"] != run_id] + [{"run_id": run_id, "status": status}]
        reg[pid] = entry
    for pid, entry in reg.items():
        if pid in seen or entry.get("current_status") == "RESOLVED":
            continue
        misses = entry.get("consecutive_misses", 0) + 1
        entry["consecutive_misses"] = misses
        if misses >= 2:
            entry["current_status"] = "RESOLVED"
            entry["history"].append({"run_id": run_id, "status": "RESOLVED"})
    for pid in seen:
        reg[pid]["consecutive_misses"] = 0
    reg_path.write_text(json.dumps(reg, indent=2, ensure_ascii=False))

    dec_path = MEM / "decisions_log.json"
    decs = load(dec_path, {})
    for d in snap.get("decisions", []):
        prev = decs.get(d["id"], {})
        merged = {**d, "run_id": run_id}
        # never overwrite a recorded human decision or outcome with PENDING/null
        if prev.get("human_approval") in ("APPROVED", "REJECTED") and d.get("human_approval") == "PENDING":
            merged["human_approval"] = prev["human_approval"]
        if prev.get("outcome") and not d.get("outcome"):
            merged["outcome"] = prev["outcome"]
        decs[d["id"]] = merged
    dec_path.write_text(json.dumps(decs, indent=2, ensure_ascii=False))

    print(f"merged {run_id}: {len(runs)} run(s) in memory, "
          f"{len(reg)} problems in registry, {len(decs)} decisions logged")


if __name__ == "__main__":
    main(sys.argv[1])
