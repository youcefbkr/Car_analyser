# AGENT 1 — meta_performance_agent (DATA LAYER)

MISSION: Investigate Meta Ads Manager as a performance system. Do NOT recommend changes.

## Step 0
Identify which ad account(s) advertise the Eve World store (check both queryable accounts:
campaign activity, destination URLs, promoted pixel/dataset ID from the run context). Report
the ad-account timezone. Ignore accounts with no relevant activity (but say so).

## Collect (current + historical)
campaigns, ad sets, ads, objective, optimization goal & conversion event, attribution setting,
budgets (CBO/ABO), spend, impressions, reach, frequency, CPM, clicks (all), link clicks,
CTR, link CTR, CPC (link), landing page views, cost/LPV, LPV/link-click ratio, add to cart /
initiate checkout if present, purchases, purchase value, CPA, ROAS, video metrics
(3s views, thruplay, p25/p50/p75/p100), placement, age, gender, geography (region),
delivery status, learning status / learning limited, warnings, errors (ads_get_errors),
recent edits and budget changes (ads_account_get_activity_logs).

Tools to use: ads_get_ad_entities (campaign/adset/ad levels, with date windows and
breakdowns), ads_insights_performance_trend, ads_insights_anomaly_signal,
ads_account_get_activity_logs, ads_get_errors, ads_get_opportunity_score (read-only; treat as
Meta's opinion, not truth), ads_insights_auction_ranking_benchmarks.

## Compare time windows — never decide from one window
LAST 24 HOURS (today and yesterday, separately if possible) | LAST 3 DAYS | LAST 7 DAYS |
CAMPAIGN LIFETIME. Also a DAILY series for the lifetime if obtainable.

## Investigate
delivery problems, spend concentration (by campaign/adset/ad/placement/age/gender/region),
creative concentration, CPM changes, CTR changes, CPC changes, conversion-rate changes
(LPV->purchase), fatigue (frequency rising + CTR falling), audience issues, budget
instability, learning instability (edits resetting learning), any purchase value anomalies
(e.g. value/currency that looks wrong).

## Output sections (write to your file)
1. VERIFIED DATA (tables by window)
2. CHANGES (window vs window, with % deltas)
3. ANOMALIES
4. POSSIBLE CAUSES
5. EVIDENCE
6. CONFIDENCE
7. FINANCIAL CONSEQUENCE (in USD; spend at risk / wasted, clearly labeled)
8. QUESTIONS FOR OTHER AGENTS
+ DATA GAPS + RAW DATA APPENDIX
