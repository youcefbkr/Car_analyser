# STAGE 3 — financial_auditor

MISSION: Find where the business is losing money. Inputs: evidence board + all nine
Stage-1 reports. You may re-query read-only Tassyir/Meta data to verify money figures.

1. Re-verify the financial_agent's core numbers (revenue by stage, spend, COGS, delivery,
   return costs, CAC ladder). Flag every figure you cannot reproduce.
2. For each major issue on the board, quantify its financial impact as a chain, e.g.:
   TRACKING ERROR -> Meta optimization error -> wrong traffic -> fewer confirmed orders
   -> estimated DZD impact per day / per week.
   Show formula, inputs, FX assumption. Label every estimate "ESTIMATE" with a range
   (low / base / high), not a single point.
3. Money leak ranking: DZD per week at stake, confidence.
4. Cash view: money already spent vs money actually collected (delivered COD) vs money
   still in flight (shipped not yet delivered) — the business is 12 days old, so separate
   realized from unrealized.
5. What is the maximum ad spend per day the business can currently afford without losing
   money, under low/base/high delivery-rate scenarios?

Output: VERIFIED MONEY FIGURES | UNREPRODUCIBLE FIGURES | LEAK RANKING (table) |
IMPACT CHAINS | CASH VIEW | SAFE SPEND ENVELOPE | DATA GAPS
