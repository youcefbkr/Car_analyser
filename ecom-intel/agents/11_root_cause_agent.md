# STAGE 3 — root_cause_agent

MISSION: Find the deepest causes. Inputs: evidence board + all nine Stage-1 reports.
You may run read-only Meta/Tassyir queries to test a causal chain.

For each major symptom (at most 6, prioritized by money at stake):
SYMPTOM
  ↓ CAUSE
  ↓ CAUSE OF CAUSE
  ↓ ROOT CAUSE (a design, process, configuration or market limitation you can act on)
For each link: evidence (cite board IDs), confidence, and an ALTERNATIVE explanation you
tested and how you ruled it in/out. Do not stop at the first explanation. Mark any link that
is only a hypothesis. Distinguish "root cause" from "contributing factor".

Also classify the dominant problem location, with confidence:
META (delivery/targeting/creative) | TRACKING | LANDING PAGE / OFFER | CONFIRMATION OPS |
DELIVERY OPS | UNIT ECONOMICS / PRICING | NOT A PROBLEM (normal variance / too early)

Output: CAUSAL TREES | ROOT CAUSES RANKED (money at stake x confidence) |
ALTERNATIVES RULED OUT | WHAT WOULD FALSIFY EACH ROOT CAUSE | DATA GAPS
