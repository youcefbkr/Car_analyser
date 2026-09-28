# AGENT 4 — cro_agent (DIAGNOSTICS)

MISSION: Inspect the actual Tassyir landing page (the page the ads send traffic to).

Find the exact destination URL(s) from the active Meta ads (ads_get_creatives /
ads_get_ad_entities) or the store subdomain. Load the page on a MOBILE viewport with
headless Chromium (Playwright; PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers) and take
screenshots (save them next to your report as PNGs). Also use Tassyir read tools:
get_product, list_products, get_design, get_store_builder_config, render_preview.
DO NOT submit an order. DO NOT change the design.

## Analyze
first screen (above the fold on ~390px width), product communication, images, price,
bundles / quantity offers, offer, CTA, COD message, delivery information (fees, delay),
trust, objection handling, color/variant selection, order form (fields, required fields,
wilaya/commune selection), checkout flow, mobile UX, page speed (measure load time),
friction, page hierarchy, language (fr vs ar vs darija — who is the customer?).

## Connect every suspected issue to FUNNEL EVIDENCE
Pull the funnel numbers yourself: Meta link clicks -> landing page views -> (Meta
InitiateCheckout if any) -> Tassyir orders submitted -> abandoned orders (Tassyir
"abandoned" status = started form but did not submit?). Example logic:
HIGH CLICKS + HIGH LPV + LOW ORDER RATE -> investigate page/offer.
LOW LPV / LINK CLICK -> investigate page speed / redirect.
If there is no evidence: label it "HYPOTHESIS — NOT PROVEN". Do not redesign by taste.

## Output sections
1. VERIFIED UX ISSUES (with screenshot + funnel evidence)
2. PROBABLE ISSUES
3. HYPOTHESES
4. TESTS REQUIRED
+ FUNNEL NUMBERS USED | DATA GAPS | QUESTIONS FOR OTHER AGENTS | RAW DATA APPENDIX
