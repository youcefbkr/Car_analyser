# CLAUDE.md

## E-commerce Intelligence Workflow (`ecom-intel/`)

A multi-agent business-intelligence workflow for the owner's Algerian COD store (Meta Ads →
Tassyir store → phone confirmation → ZR Express delivery). Read `ecom-intel/README.md` for the
architecture and run modes, and `ecom-intel/agents/` for every agent's mission.

### Where the memory lives (the owner asked Claude to remember this)
- The workflow's history is kept **on the owner's laptop**, inside the local clone of this repo:
  - `ecom-intel/memory/` — `snapshots.jsonl`, `problem_registry.json`, `decisions_log.json`,
    `owner_facts.json` (owner-verified costs, answers and approved decisions)
  - `ecom-intel/runs/<date>_<mode>/` — each run's context, agent reports, executive report
    (English + Arabic) and `snapshot.json`
- Both folders are **git-ignored on purpose**: they hold private business data and this repo is
  public. Never commit or push them, and never copy their numbers into committed files.
- **Before every run, load the memory first.** If `ecom-intel/memory/owner_facts.json` is missing
  (e.g. a fresh cloud session), stop and ask the owner to upload the latest
  `ecom-intel-private-*.zip` from the laptop folder and extract it at the repo root. Do not start a
  run as if it were the first one.
- **After every run**, merge the snapshot (`python3 ecom-intel/tools/merge_memory.py
  ecom-intel/runs/<run_id>/snapshot.json`), record the owner's approvals in
  `memory/decisions_log.json`, and — if running in the cloud — send the owner a fresh
  `ecom-intel-private-<date>.zip` of `ecom-intel/memory/` + `ecom-intel/runs/` to save back into
  the same laptop folder.

### Standing rules
- All agents are READ-ONLY on Meta and Tassyir. Every action is a proposal that waits for the
  owner's explicit approval; record approvals with their date.
- Money in DZD at the owner's real Meta rate (see `memory/owner_facts.json`), never Meta's
  internal conversion rate. Decisions use Tassyir confirmed/delivered orders, never Meta ROAS/CPA.
- No customer names, phones or addresses in any file.
- The owner reads the executive report in **Arabic**: produce `executive_report_ar.html`
  (right-to-left) alongside the English report.
- Never submit test orders on the live storefront.
