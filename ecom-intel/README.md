# E-commerce Intelligence Workflow (Meta Ads × Tassyir × Landing page × COD operations)

A multi-agent business-intelligence workflow. The main Claude Code session is the ORCHESTRATOR;
every analyst is a real, independent subagent launched with the `Agent` tool, with its own
isolated context, reading only the files it is told to read.

Objective: maximize real profit from DELIVERED, NON-RETURNED orders — not clicks, not
Meta-reported purchases, not ROAS alone.

All agents are READ-ONLY on Meta and Tassyir. Every action is proposed and waits for human
approval.

## Architecture
```
ORCHESTRATOR
│
├─ STAGE 1A (parallel, independent — each pulls its own raw data)
│   DATA LAYER:   meta_performance_agent · tassyir_operations_agent · tracking_forensics_agent
│   DIAGNOSTICS:  cro_agent · creative_intelligence_agent
│   BUSINESS:     financial_agent · customer_delivery_agent
├─ STAGE 1B (parallel, reads 1A)  experimentation_agent · adversarial_agent
├─ STAGE 2   evidence_board_compiler → FACTS / HYPOTHESES / CONTRADICTIONS / ANOMALIES /
│            FINANCIAL / TECHNICAL / MARKETING / OPERATIONAL / UNKNOWNS
├─ STAGE 3 (parallel)  root_cause_agent · financial_auditor · technical_auditor
├─ STAGE 4 (parallel, then rebuttal round)  media_buyer_reviewer · cfo_reviewer · cto_reviewer
└─ STAGE 5   chief_growth_officer → DAILY EXECUTIVE REPORT + memory snapshot
```

## Files
- `agents/_shared_rules.md` — binding rules for every agent (read-only, privacy, evidence tags)
- `agents/NN_<agent>.md` — each agent's mission
- `memory/SCHEMA.md` — snapshot + problem registry format (memory data itself is git-ignored)
- `runs/<date>_<mode>/` — per-run context, reports, snapshot (git-ignored: private business data)

## Run modes
### MODE B — DEEP INVESTIGATION
All stages above. Use when performance suddenly changes, tracking looks wrong, profitability
changes, the campaign is hard to diagnose, or a major decision is required.

### MODE A — DAILY CHECK (fast)
1. Orchestrator writes `runs/<date>_daily/context.md` (+ the previous snapshot path).
2. Parallel: meta_performance_agent, tassyir_operations_agent, financial_agent —
   each told to focus on "what changed since the previous snapshot / yesterday".
   tracking_forensics_agent runs only if Meta purchases vs Tassyir orders diverge by >25%
   from the previous run's ratio.
3. adversarial_agent attacks the three reports.
4. chief_growth_officer produces the executive report, comparing every KPI and problem against
   `memory/` and tagging problems NEW / OLD / IMPROVING / WORSENING / RESOLVED / RECURRING.
5. Escalate to MODE B automatically if any trigger above fires.

## Orchestrator checklist (every run)
1. Discover IDs (ad accounts, store) and write run context — no analysis.
2. Load the previous snapshot + problem registry and pass their paths to every agent.
3. Launch stages in dependency order; verify each report file exists and follows its template.
4. After Stage 5, merge snapshot into memory; present the report; WAIT FOR HUMAN APPROVAL.
