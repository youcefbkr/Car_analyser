# HISTORICAL MEMORY — schema

Memory lives in `ecom-intel/memory/` (git-ignored: it contains private business data).
Each run writes `runs/<date>_<mode>/snapshot.json` and the orchestrator merges it into:

- `memory/snapshots.jsonl` — one line per run (the snapshot object below)
- `memory/problem_registry.json` — every problem ever detected, keyed by stable ID
- `memory/decisions_log.json` — every proposed action + the human's decision + outcome

## snapshot.json
```json
{
  "run_id": "2026-09-28_deep",
  "date": "2026-09-28",
  "mode": "A_daily | B_deep",
  "previous_run_id": null,
  "fx_assumption": {"dzd_per_usd": null, "source": "owner | assumed", "scenarios": []},
  "kpis": {
    "<window: last_24h | last_3d | last_7d | lifetime>": {
      "meta": {"spend_usd": 0, "impressions": 0, "reach": 0, "frequency": 0, "cpm": 0,
               "link_clicks": 0, "ctr_link": 0, "cpc_link": 0, "lpv": 0,
               "meta_purchases": 0, "meta_purchase_value": 0, "meta_cpa": 0, "meta_roas": 0},
      "tassyir": {"orders": 0, "pending": 0, "confirmed": 0, "canceled": 0, "abandoned": 0,
                  "shipped": 0, "delivered": 0, "returned": 0, "in_flight": 0,
                  "revenue_submitted_dzd": 0, "revenue_delivered_dzd": 0},
      "economics": {"confirmed_cac": null, "delivered_cac": null, "profitable_cac": null,
                    "contribution_profit_dzd_range": [null, null]}
    }
  },
  "tracking_health": {"overall": "GREEN|YELLOW|RED", "pixel": "", "capi": "",
                      "purchase_event_timing": "", "attribution": ""},
  "problems": [
    {"id": "P-001", "title": "", "area": "META|TRACKING|LANDING|OPS_CONFIRM|OPS_DELIVERY|ECONOMICS",
     "severity": "H|M|L", "confidence": "H|M|L", "money_at_stake_dzd_week": [null, null],
     "evidence_refs": [], "status_vs_previous": "NEW|OLD|IMPROVING|WORSENING|RESOLVED|RECURRING"}
  ],
  "hypotheses": [{"id": "H-001", "statement": "", "test": "", "status": "OPEN|CONFIRMED|REJECTED"}],
  "decisions": [{"id": "D-001", "target": "", "decision": "SCALE|KEEP|WATCH|TEST|REDUCE|PAUSE|FIX TRACKING|FIX LANDING PAGE|FIX OPERATIONS|DO NOTHING YET",
                 "proposed_action": "", "why": "", "confidence": "", "falsifier": "",
                 "human_approval": "PENDING|APPROVED|REJECTED", "outcome": null}],
  "experiments": [{"id": "E-001", "hypothesis": "", "status": "PROPOSED|RUNNING|DONE", "result": null}],
  "unresolved_questions": [""]
}
```

## Problem status rules (applied by the orchestrator on every run)
- NEW: not in registry.
- OLD: in registry, metric roughly unchanged (±10%).
- IMPROVING / WORSENING: in registry, key metric moved >10% in the good / bad direction.
- RESOLVED: in registry, no longer detected for 2 consecutive runs.
- RECURRING: was RESOLVED, detected again.
