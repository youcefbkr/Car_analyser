"""One hourly run: detect status transitions, decide, claim, send, record.

A run has up to three steps, each followed by the Routine saving the output:

  plan   read-only; lists the orders about to get an SMS so the Routine can
         re-read each one with get_order (a second, independent read)
  claim  records every status change; for each verified SMS it writes a
         'sending' claim. The claims are saved BEFORE anything is sent.
  send   (only when claims exist) re-reads the saved claims, sends with one
         automatic retry, and records the result.

Because a claim is durable before its SMS leaves, a crash or a failed save can
never lead to a second SMS for the same order + status; the worst case is a
claim left 'unconfirmed', which raises an alert instead of re-sending.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import statuses as st
from .phone import InvalidPhone, normalize_dz_phone
from .providers import DryRunProvider
from .statuses import map_status, raw_label
from .store import ledger_key, month_of
from .templates import TemplateError, clean_name, format_total, render, segment_info

REAL_ORDER_STATUSES = {"pending", "confirmed", "dispatched", "scheduled", "delivered"}
RESULT_BY_MODE = {"dry_run": "dry_run", "test": "test_sent"}
RECONCILE_WINDOW = timedelta(hours=48)


def parse_ts(value):
    text = value.strip().replace("Z", "+00:00")
    ts = datetime.fromisoformat(text)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def iso(ts):
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_month(month, delta):
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass
class Summary:
    run_id: str
    started_at: str
    mode: str
    phase: str = "plan"
    baseline: bool = False
    orders_checked: int = 0
    status_changes: int = 0
    sms_planned: int = 0
    sms_sent: int = 0
    sms_failed: int = 0
    skipped: int = 0
    invalid_phones: int = 0
    api_errors: int = 0
    deferred: int = 0
    already_notified: int = 0
    errors: list = field(default_factory=list)
    unknown_statuses: list = field(default_factory=list)
    awaiting_verification: list = field(default_factory=list)
    verification_mismatches: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    finished_at: str = None

    def to_dict(self):
        return dict(self.__dict__)

    def alert(self, title, body):
        self.alerts.append({"title": title, "body": body})


class Engine:
    def __init__(self, store, settings, provider=None, now=None, sleep=time.sleep):
        self.store = store
        self.settings = settings
        self.provider = provider if provider is not None else DryRunProvider()
        self.now = now or datetime.now(timezone.utc)
        self.sleep = sleep
        self.run_id = self.now.strftime("%Y%m%dT%H%M%SZ")
        self.summary = Summary(run_id=self.run_id, started_at=iso(self.now), mode=settings.mode)
        self.first_active_month = shift_month(self.now.strftime("%Y-%m"), -(settings.retention_months - 1))

    # ------------------------------------------------------------------
    # decisions

    def _evaluate(self, order):
        """Return (kind, auto_status, previous_record, reason)."""
        auto, known = map_status(order)
        raw = raw_label(order)
        if not known and raw not in self.summary.unknown_statuses:
            self.summary.unknown_statuses.append(raw)
        if month_of(order.created_at) < self.first_active_month:
            return "too_old", auto, None, None
        prev = self.store.get_order(order.id, order.created_at)
        if prev is None or prev.get("raw") != raw:
            self.summary.status_changes += 1
        if auto is None:
            return "record", auto, prev, None
        if self.store.get_ledger(order.id, order.created_at, auto):
            if prev is None or prev.get("s") != auto:
                self.summary.already_notified += 1
            return "record", auto, prev, None
        baseline_at = parse_ts(self.store.meta["baseline_at"])
        if prev is None and parse_ts(order.created_at) < baseline_at:
            return "baseline", auto, prev, "order existed before the automation started"
        if order.is_spam or order.is_banned:
            return "skip", auto, prev, "order marked spam or customer banned in Tassyir"
        if auto == st.CANCELLED:
            seen = {s.lower() for s in order.history}
            if prev:
                seen.add((prev.get("raw") or "").split("/")[0])
            if seen and not seen & REAL_ORDER_STATUSES:
                return "skip", auto, prev, "abandoned checkout, never a real order"
        rank = st.FORWARD_RANK.get(auto)
        if rank:
            higher = [s for s in self.store.ledger_for_order(order.id, order.created_at)
                      if st.FORWARD_RANK.get(s, 0) > rank]
            if higher or st.FORWARD_RANK.get((prev or {}).get("s"), 0) > rank:
                return "skip", auto, prev, "order already reached a later stage"
        return "candidate", auto, prev, None

    def _order_record(self, order, auto, prev):
        raw = raw_label(order)
        changed = prev is None or prev.get("raw") != raw
        return {
            "n": order.number,
            "c": order.created_at,
            "raw": raw,
            "s": auto,
            "seen": iso(self.now),
            "chg": iso(self.now) if changed else prev.get("chg"),
        }

    # ------------------------------------------------------------------
    # step 1: plan

    def plan(self, snapshot):
        """Order ids that will get an SMS this run and need a get_order re-read."""
        self.summary.orders_checked = len(snapshot.orders)
        if not self.store.has_baseline:
            self.summary.baseline = True
            return []
        wanted = []
        for order in snapshot.orders:
            try:
                kind, *_ = self._evaluate(order)
            except Exception as exc:  # one bad order never stops the run
                self.summary.errors.append(f"{order.id}: {exc}")
                continue
            if kind == "candidate":
                if len(wanted) >= self.settings.max_per_run:
                    self.summary.deferred += 1
                else:
                    wanted.append(order.id)
        return wanted

    # ------------------------------------------------------------------
    # step 2: claim

    def claim(self, snapshot, verifications):
        s = self.summary
        s.phase = "claim"
        s.orders_checked = len(snapshot.orders)
        s.api_errors = len(snapshot.errors)
        if snapshot.errors:
            s.alert("⚠️ Eve World SMS: Tassyir read failed",
                    "Some Tassyir calls failed this hour; affected orders are checked next run.\n"
                    + "\n".join(snapshot.errors))
        if not self.store.has_baseline:
            return self._baseline(snapshot)

        meta = self.store.ensure_meta()
        self._settle_interrupted(meta)
        self._reconcile_queued()
        self.store.deactivate_months_before(self.first_active_month)

        pending = []
        for order in snapshot.orders:
            try:
                self._claim_order(order, verifications, pending)
            except Exception as exc:
                s.errors.append(f"{order.number or order.id}: {type(exc).__name__}: {exc}")
        meta["pending"] = pending
        s.sms_planned = len(pending)
        meta.update({"mode": self.settings.mode, "provider": self.provider.name,
                     "template_set": self.settings.template_set})
        if s.verification_mismatches:
            s.alert("⚠️ Eve World SMS: Tassyir data mismatch",
                    "Two reads of these orders disagreed, so no SMS was sent. They are retried next run:\n"
                    + "\n".join(s.verification_mismatches))
        if s.errors:
            s.alert("⚠️ Eve World SMS: order errors", "\n".join(s.errors))
        if pending:
            s.phase = "claimed"
            meta["current_run"] = s.to_dict()
        else:
            self._finish(meta)
        return pending

    def _claim_order(self, order, verifications, pending):
        s = self.summary
        kind, auto, prev, reason = self._evaluate(order)
        if kind == "too_old":
            return
        if kind == "record":
            self.store.put_order(order.id, order.created_at, self._order_record(order, auto, prev))
            return
        if kind == "baseline":
            self.store.put_ledger(order.id, order.created_at, auto, {"r": "baseline", "t": iso(self.now), "why": reason})
            self.store.put_order(order.id, order.created_at, self._order_record(order, auto, prev))
            return
        if kind == "skip":
            s.skipped += 1
            self._finalize(order, auto, prev, "skipped", reason=reason)
            return

        # candidate
        if len(pending) >= self.settings.max_per_run:
            s.deferred += 1
            return
        verify = verifications.get(order.id)
        if verify is None:
            s.awaiting_verification.append(order.id)
            return
        problems = _compare(order, verify)
        if problems:
            s.verification_mismatches.append(f"{order.number}: {', '.join(problems)}")
            return
        try:
            phone = normalize_dz_phone(verify.phone)
        except InvalidPhone as exc:
            s.invalid_phones += 1
            self._finalize(order, auto, prev, "invalid_phone", reason=str(exc), phone_raw=verify.phone)
            return
        try:
            message = render(auto, verify.name, verify.total, self.settings.template_set)
        except TemplateError as exc:
            s.skipped += 1
            self._finalize(order, auto, prev, "skipped", reason=str(exc), phone=phone)
            s.alert("⚠️ Eve World SMS: order data problem", f"Order {order.number}: {exc}")
            return

        send_to = normalize_dz_phone(self.settings.test_phone) if self.settings.mode == "test" else phone
        claim = {
            "key": ledger_key(order.id, auto),
            "order_id": order.id,
            "order_number": order.number,
            "created_at": order.created_at,
            "status": auto,
            "previous_status": (prev or {}).get("s"),
            "current_status": raw_label(order),
            "customer_name": clean_name(verify.name),
            "phone_raw": verify.phone,
            "phone_number": phone,
            "send_to": send_to,
            "total_price": int(format_total(verify.total)) if verify.total else None,
            "message": message,
            "segments": segment_info(message)[2],
            "claim_run": self.run_id,
            "claimed_at": iso(self.now),
        }
        self.store.put_ledger(order.id, order.created_at, auto,
                              {"r": "sending", "t": iso(self.now), "claim": self.run_id})
        self.store.put_order(order.id, order.created_at, self._order_record(order, auto, prev))
        pending.append(claim)

    def _finalize(self, order, auto, prev, result, reason=None, phone=None, phone_raw=None):
        """Record a notification that ends without sending (skipped / invalid phone)."""
        self.store.put_ledger(order.id, order.created_at, auto, {"r": result, "t": iso(self.now), "why": reason})
        self.store.put_order(order.id, order.created_at, self._order_record(order, auto, prev))
        self.store.add_log(_log_id(order.id, auto), {
            "order_id": order.id, "order_number": order.number, "status": auto,
            "previous_status": (prev or {}).get("s"), "current_status": raw_label(order),
            "customer_name": clean_name(order.name), "phone_raw": phone_raw or order.phone,
            "phone_number": phone, "total_price": order.total, "message": None,
            "provider": self.provider.name, "mode": self.settings.mode, "attempt_count": 0,
            "result": result, "error": reason, "created_at": iso(self.now), "sent_at": None,
        })

    def _baseline(self, snapshot):
        s = self.summary
        s.baseline = True
        s.phase = "baseline"
        if not snapshot.complete:
            s.alert("⚠️ Eve World SMS: baseline postponed",
                    "The first run needs a complete read of Tassyir; it will try again next hour.")
            s.finished_at = iso(max(self.now, datetime.now(timezone.utc)))
            self.store.add_run(s.run_id, s.to_dict())
            return []
        meta = self.store.ensure_meta()
        meta.update({"baseline_at": snapshot.fetched_at, "pending": [], "mode": self.settings.mode,
                     "provider": self.provider.name, "template_set": self.settings.template_set})
        for order in snapshot.orders:
            try:
                auto, known = map_status(order)
                if not known and raw_label(order) not in s.unknown_statuses:
                    s.unknown_statuses.append(raw_label(order))
                if month_of(order.created_at) < self.first_active_month:
                    continue
                self.store.put_order(order.id, order.created_at, self._order_record(order, auto, None))
                if auto:
                    self.store.put_ledger(order.id, order.created_at, auto, {
                        "r": "baseline", "t": iso(self.now), "why": "status at automation start"})
            except Exception as exc:
                s.errors.append(f"{order.id}: {exc}")
        self._finish(meta)
        return []

    def _settle_interrupted(self, meta):
        """Claims left by a run that stopped before recording its result."""
        for claim in meta.get("pending") or []:
            entry = self.store.get_ledger(claim["order_id"], claim["created_at"], claim["status"])
            if entry and entry.get("r") == "sending":
                entry.update({"r": "unconfirmed", "why": "run stopped after claiming; SMS may or may not have gone out"})
                self.store.touch_month(month_of(claim["created_at"]))
                self.summary.alert("⚠️ Eve World SMS unconfirmed", _alert_body(claim, 0, entry["why"]))
        meta["pending"] = []

    def _reconcile_queued(self):
        """Ask the provider what happened to SMS the phone had not sent yet."""
        for month, order_id, status, entry in list(self.store.iter_ledger()):
            if entry.get("r") != "queued" or not entry.get("p"):
                continue
            if self.now - parse_ts(entry["t"]) > RECONCILE_WINDOW:
                continue
            try:
                state = self.provider.check(entry["p"])
            except Exception:
                continue
            if state in ("Sent", "Delivered"):
                entry.update({"r": state.lower(), "t2": iso(self.now)})
                self.store.touch_month(month)
            elif state == "Failed":
                entry.update({"r": "failed", "t2": iso(self.now), "why": "phone reported Failed after queueing"})
                self.store.touch_month(month)
                self.summary.sms_failed += 1
                self.summary.alert("⚠️ Eve World SMS failed",
                                   f"Order id {order_id} ({status}): the phone could not send the queued SMS.")

    # ------------------------------------------------------------------
    # step 3: send

    def send(self):
        meta = self.store.meta or {}
        pending = meta.get("pending") or []
        previous = meta.get("current_run") or {}
        s = self.summary
        for name in ("orders_checked", "status_changes", "skipped", "invalid_phones", "api_errors", "deferred",
                     "already_notified", "sms_planned"):
            setattr(s, name, previous.get(name, getattr(s, name)))
        for name in ("errors", "unknown_statuses", "verification_mismatches", "alerts"):
            setattr(s, name, list(previous.get(name) or []))
        s.run_id = previous.get("run_id", s.run_id)
        s.started_at = previous.get("started_at", s.started_at)
        s.phase = "sent"

        for i, claim in enumerate(pending):
            entry = self.store.get_ledger(claim["order_id"], claim["created_at"], claim["status"])
            if not entry or entry.get("r") != "sending" or entry.get("claim") != claim["claim_run"]:
                s.errors.append(f"{claim['order_number']}: claim not found in saved state; not sent")
                continue
            if i:
                self.sleep(2)  # space messages out a little for the phone
            result, attempts, error, pmid = self._send_with_retry(claim)
            entry.update({"r": result, "t": iso(self.now), "a": attempts, "p": pmid, "why": error})
            entry.pop("claim", None)
            self.store.touch_month(month_of(claim["created_at"]))
            self.store.add_log(_log_id(claim["order_id"], claim["status"]), {
                **{k: claim[k] for k in ("order_id", "order_number", "status", "previous_status", "current_status",
                                         "customer_name", "phone_raw", "phone_number", "total_price", "message",
                                         "segments")},
                "sent_to": claim["send_to"], "provider": self.provider.name, "mode": self.settings.mode,
                "attempt_count": attempts, "result": result, "error": error, "provider_message_id": pmid,
                "created_at": claim["claimed_at"], "sent_at": iso(self.now) if result != "failed" else None,
            })
            if result == "failed":
                s.sms_failed += 1
                s.alert("⚠️ Eve World SMS failed", _alert_body(claim, attempts, error))
            else:
                s.sms_sent += 1
        meta["pending"] = []
        meta.pop("current_run", None)
        if s.errors:
            s.alert("⚠️ Eve World SMS: send problems", "\n".join(s.errors))
        self._finish(self.store.ensure_meta())

    def _send_with_retry(self, claim):
        error = None
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                res = self.provider.send(claim["send_to"], claim["message"], claim["key"], attempt)
            except Exception as exc:
                res = None
                error = f"{type(exc).__name__}: {exc}"
            if res is not None and res.ok:
                state = res.state or "sent"
                result = RESULT_BY_MODE.get(self.settings.mode, state if state in ("queued", "delivered") else "sent")
                return result, attempt, None, res.provider_message_id
            if res is not None:
                error = res.error or "unknown provider error"
            if attempt < self.settings.max_attempts:
                self.sleep(self.settings.retry_delay)
        return "failed", self.settings.max_attempts, error, None

    # ------------------------------------------------------------------

    def _finish(self, meta):
        s = self.summary
        s.finished_at = iso(max(self.now, datetime.now(timezone.utc)))
        if s.phase not in ("baseline", "sent"):
            s.phase = "done"
        meta["last_run"] = s.to_dict()
        self.store.dirty.add("meta")
        self.store.add_run(s.run_id, s.to_dict())


def _compare(order, verify):
    """Fields that differ between the list read and the get_order read."""
    problems = []
    if (verify.status or "").lower() != (order.status or "").lower():
        problems.append(f"status {order.status!r} vs {verify.status!r}")
    try:
        a, b = normalize_dz_phone(order.phone), normalize_dz_phone(verify.phone)
    except InvalidPhone:
        a, b = (order.phone or "").strip(), (verify.phone or "").strip()
    if a != b:
        problems.append("phone")
    one_missing = (order.total is None) != (verify.total is None)
    if one_missing or (order.total is not None and abs(float(order.total) - float(verify.total)) >= 0.5):
        problems.append(f"total {order.total} vs {verify.total}")
    if clean_name(order.name) != clean_name(verify.name):
        problems.append("name")
    return problems


def _log_id(order_id, status):
    return f"{order_id}_{status}"


def _alert_body(claim, attempts, error):
    label = {st.CONFIRMED: "Confirmed", st.DELIVERY_DESK: "Delivered to delivery desk",
             st.DELIVERED: "Delivered", st.CANCELLED: "Cancelled", st.RETURNED: "Returned"}
    return (
        f"Order: {claim['order_number']}\n"
        f"Customer: {claim['customer_name'] or '-'}\n"
        f"Status: {label.get(claim['status'], claim['status'])}\n"
        f"Phone: {claim['phone_number']}\n"
        f"Attempts: {attempts}\n"
        f"Error: {error}\n"
        f"Message:\n{claim['message']}"
    )
