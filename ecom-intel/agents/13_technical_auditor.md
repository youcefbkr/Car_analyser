# STAGE 3 — technical_auditor

MISSION: Investigate every technical dependency that could INVALIDATE the marketing data.
Inputs: evidence board + all nine Stage-1 reports. You may re-query read-only Meta dataset /
pixel / event tools, read-only Tassyir store settings and activity logs, and inspect the live
page with headless Chromium (/opt/pw-browsers/chromium). NEVER submit an order or change
settings.

Dependency map to audit, one row each:
ad click -> URL/UTM/fbclid preserved? -> page load (speed, redirects) -> pixel load (which
IDs) -> PageView/ViewContent -> form interaction events -> order submit -> browser Purchase?
-> Tassyir order record (source/UTM stored?) -> CAPI server events (which events, when:
submit/confirm/deliver) -> event_id dedup -> value/currency correctness -> Meta dataset
receiving -> ad set optimization event -> attribution window -> reporting.

For each dependency: STATUS (OK / BROKEN / UNVERIFIED) | EVIDENCE | WHAT DATA IT INVALIDATES
| SEVERITY | EXACT FIX | VERIFICATION METHOD.
Then a verdict: which Meta metrics in this account can be trusted for decisions, which
cannot, and which Tassyir metrics are the source of truth.

Output: DEPENDENCY TABLE | DATA TRUST MATRIX (metric -> trust level -> why) |
CRITICAL FIXES (ordered) | DATA GAPS
