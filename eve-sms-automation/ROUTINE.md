# Hourly run: exact procedure

This file is the procedure the hourly Claude Routine follows. Do every step
in order, do not improvise, and stop at the first failure the steps tell you
to stop on.

Rules for the whole run:
- Tassyir is read-only here. Only call `list_orders`, `list_order_tracking`,
  `list_returns` and `get_order`. Never confirm, cancel, dispatch, update or
  comment on anything.
- Never print, echo or log environment variables, passwords or API keys.
- Copy data exactly as Tassyir returns it. Never guess, fix or fill in a value.
- `DB` below means the artifact `https://claude.ai/artifact/1g7h2CAzFEfPz6caHwq4C5`.

## 0. Code and work folder

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo ~/Car_analyser)"
git fetch origin claude/tassyir-sms-order-automation-6gqhg1
git checkout -B eve-sms-run FETCH_HEAD
cd eve-sms-automation
W=$(mktemp -d /tmp/eve-sms-XXXX); mkdir -p "$W/verify"; echo "$W"
python3 -c "import requests" 2>/dev/null || pip install -q requests
```

Use the printed folder path literally wherever `$W` appears below.

## 1. Read the saved state

`ArtifactData` with `action: "query"`, `url: DB`, `collection: "sms"`,
`query: {"where": [["active", "==", true]]}`, `out_dir: "$W/db1"`.

If this call fails, stop the run and report it (nothing has been sent).

## 2. Read Tassyir

Make these read-only calls (limit 100; if `hasNextPage` is true, fetch the next
page, at most 3 pages per call):

| # | Tool | Arguments | `source` value |
|---|------|-----------|----------------|
| a | `list_orders` | `status: "confirmed"` | `orders` |
| b | `list_orders` | `status: "canceled"`, `startDate`: today minus 14 days (YYYY-MM-DD) | `orders` |
| c | `list_order_tracking` | page 1 only | `tracking` |
| d | `list_returns` | page 1 only | `returns` |

First run only: if step 1 saved no `$W/db1/sms/meta.json`, the automation has
no baseline yet. Replace calls a and b with one `list_orders` call without any
`status` filter (all pages, at most 5), so orders still pending are recorded
too. That run sends no SMS; it only records the current status of every order.

Write `$W/snapshot.json`:

```json
{"fetched_at": "<current UTC time, e.g. 2026-09-29T16:00:00Z>",
 "complete": true,
 "errors": [],
 "orders": [ ...one object per item from every call above... ]}
```

Each item becomes one object with exactly these fields:

| Snapshot field | Taken from the Tassyir item | If absent |
|---|---|---|
| `id` | `id` (string) | never absent |
| `number` | `orderNumber` | never absent |
| `created_at` | `createdAt` | never absent |
| `source` | the table above | |
| `status` | `status` | never absent |
| `tracking_status` | `trackingStatus` | `null` |
| `delivery_status` | `deliveryStatus` | `null` |
| `history` | every `statusHistory[].status`, in the order given | `[]` |
| `name` | `orderClient.name` | `""` |
| `phone` | `orderClient.phone` | `null` |
| `total` | `total` (number) | `null` |
| `is_spam` | `isSpam` | `false` |
| `is_banned` | `orderClient.isBanned` | `false` |

If any call failed, still write the file with the lists that worked, set
`"complete": false` and add `"<tool name>: <error text>"` to `errors`.

## 3. Plan

```bash
python3 -m eve_sms plan --db "$W/db1" --snapshot "$W/snapshot.json"
```

If the output has `"error"`, the snapshot is malformed: fix the transcription
from the Tassyir data you already have and re-run this step once. If it still
fails, stop and report.

## 4. Second read of each order about to get an SMS

For every id in the `verify` list, call `get_order` with that `orderId` and
write `$W/verify/<id>.json`:

```json
{"id": "<id>", "number": "<orderNumber>", "status": "<status>",
 "name": "<orderClient.name>", "phone": "<orderClient.phone>", "total": <total>}
```

## 5. Claim, then save

```bash
python3 -m eve_sms claim --db "$W/db1" --snapshot "$W/snapshot.json" --verify-dir "$W/verify" --out "$W/out1"
```

If `write_count` is above 0: read `$W/out1/writes.json` and pass its array,
unchanged, as `writes` to ONE `ArtifactData` call with `action: "batch"` and
`url: DB`.

If that batch fails, repeat the identical call once (safe: the batch is atomic
and version-pinned). If it fails again: STOP. Do not run step 6. Nothing has
been sent. Report the error.

## 6. Send, then save (only when step 5 printed `"next": "save_then_send"`)

1. `ArtifactData` query exactly as in step 1, but `out_dir: "$W/db2"`.
2. Run:
   ```bash
   python3 -m eve_sms send --db "$W/db2" --out "$W/out2"
   ```
3. Pass `$W/out2/writes.json` as `writes` to one `ArtifactData` batch call.
   If it fails, repeat the identical call once. Never run `send` again in this
   run. If it still fails, report it: the next run marks those SMS
   "unconfirmed" and raises an alert, and nothing is ever sent twice.

## 7. Alerts and report

For every line in the `push` arrays printed by steps 5 and 6, call
`PushNotification` with that line.

End with a short report: orders checked, status changes, SMS sent, failed,
skipped, invalid phones, API errors, unknown statuses, and the full text of
every alert.
