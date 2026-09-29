# Eve World: order status SMS

Every hour, this automation checks the Eve World orders in Tassyir and sends the
customer one SMS in Algerian Darija when an order becomes **confirmed**,
**reaches the delivery company**, is **delivered**, is **cancelled** or is
**returned**. Each order gets at most one SMS per status.

```
Claude Routine (hourly)
  │  reads Tassyir through Claude's Tassyir connector (read-only)
  ▼
snapshot.json ──► eve_sms plan ──► get_order re-read of each order about to be texted
  ▼
eve_sms claim ──► saves every status change + a "sending" claim  ──► private artifact DB
  ▼
eve_sms send  ──► SMS Gateway for Android (your SIM) ──► customer
  ▼                 1 automatic retry; 2nd failure ⇒ "failed" + Claude notification
saves result + log + run summary ──► private artifact DB  (dashboard: Eve World SMS)
```

## Why it is built this way

- **Tassyir has no public API or webhooks.** The only programmatic access is
  the Tassyir connector Claude already has, so the hourly fetch runs inside a
  scheduled Claude session (a Routine). All decisions are made by the tested
  Python code in `eve_sms/`, not by the model.
- **The GitHub repository is public**, so no customer data is ever committed.
  Order state, the idempotency ledger and the notification log live in the
  database of a private claude.ai artifact (readable only by the owner).
- **Two independent reads.** The model copies Tassyir data into a snapshot.
  Before any SMS, the order is read again with `get_order`; if phone, name,
  total or status differ between the two reads, nothing is sent and the order
  is retried next hour.
- **Claim before send.** The "sending" claim is saved before the SMS leaves.
  If anything fails afterwards, the next run marks that SMS "unconfirmed" and
  alerts you; it never sends it again.

## Status mapping (read from the Eve World account, 2026-09-29)

| Tassyir (order `status` / tracking `trackingStatus` / ZR Express `deliveryStatus`) | SMS |
|---|---|
| `confirmed` | Confirmed |
| `dispatched` / `to desk` / `commande_recue` (parcel registered, not yet handed over) | Confirmed |
| `dispatched` / `to desk` / `confirme_au_bureau` | At delivery company |
| `dispatched` / `in transit` / `dispatch`, `vers_wilaya` | At delivery company |
| `dispatched` / `out for delivery` / `sortie_en_livraison` | At delivery company |
| `delivered` / `delivered` / `livre`, `encaisse` | Delivered |
| `canceled` | Cancelled |
| in `list_returns`, or `returned` | Returned |
| `pending`, `scheduled`, `abandoned`, custom `test` | no SMS |

Tassyir confirms and dispatches an order within seconds, so an hourly run
usually sees `commande_recue` rather than `confirmed`; both send the
"confirmed" SMS. Any value not in this table is never guessed: it is listed
under "unknown statuses" in the run report so the mapping in
`eve_sms/statuses.py` can be extended.

Other rules: an order that skips stages between two runs gets only the SMS for
its current stage; an earlier-stage SMS is never sent after a later one;
orders marked spam, banned customers and cancelled abandoned checkouts are
not texted.

## SMS templates

Arabic forces UCS-2 encoding (70 characters per SMS, 67 per part when split),
so every message is at least 2 SMS parts. The default `compact` set stays at
2 parts even with a 20-character name; the original wording (`full`) reaches 3
parts with longer names. Run `python3 -m eve_sms preview` to see them.

```
Salam Sara
طلبك من Eve World تأكد ✅
المبلغ الإجمالي: 2900 DA
راح نعلموك بكل جديد.
Instagram: @eve_worlld
```

The amount is always the order `total` from Tassyir, which already includes
delivery.

## First run

The first run (done on 2026-09-29 at 15:56 UTC) records the current status of
every order and sends nothing. Orders already confirmed, dispatched, delivered
or cancelled at that moment can never receive a historical SMS. Only changes
after that moment produce SMS.

## Settings (environment variables of the Claude cloud environment)

| Variable | Meaning |
|---|---|
| `EVE_SMS_MODE` | `dry_run` (default, sends nothing), `test` (every SMS goes to `EVE_SMS_TEST_PHONE`), `live` |
| `EVE_SMS_TEST_PHONE` | your own number, for `test` mode |
| `SMSGATE_USERNAME`, `SMSGATE_PASSWORD` | from the SMS Gateway app, "Cloud server" screen |
| `EVE_SMS_TEMPLATES` | `compact` (default) or `full` |
| `EVE_SMS_MAX_PER_RUN` | SMS per hourly run, default 10 (the rest wait for the next hour) |

Credentials are only read from the environment and never written to logs,
the database or git.

## Scheduler

The Claude Routine **"Eve World SMS – hourly Tassyir check"** fires every hour
at minute 59 (UTC) and starts a fresh Claude session that follows
`ROUTINE.md`. A status change is therefore texted at the next hourly run, not
instantly (up to about an hour later). A test fire on 2026-09-29 cloned the
code, read and saved the database with correct version pins, and raised the
expected alert because the Routine had no Tassyir connector yet. That run
used about 72k tokens of context; expect somewhat more once Tassyir data is
included, 24 times a day, counted against your Claude plan.

## Going live

0. In claude.ai → Routines → "Eve World SMS – hourly Tassyir check": attach
   the **Tassyir** connector, then turn the Routine on (it was paused so it
   would not alert you every hour while it cannot reach Tassyir).
1. Install **SMS Gateway for Android** (github.com/capcom6/android-sms-gateway)
   on an Android phone with the SIM that will send the SMS; enable
   "Cloud server" and note the username and password it shows. Keep the phone
   charged and online. A SIM plan with unlimited national SMS keeps the cost
   flat.
2. In the Claude cloud environment settings: allow the host `api.sms-gate.app`
   in Network access, and add `SMSGATE_USERNAME`, `SMSGATE_PASSWORD`,
   `EVE_SMS_MODE=test` and `EVE_SMS_TEST_PHONE=<your number>`.
3. Wait for a status change (or change a test order) and check that your own
   phone receives the SMS.
4. Set `EVE_SMS_MODE=live`.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest -q
```

`ROUTINE.md` is the exact procedure the hourly Routine follows.
