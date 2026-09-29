"""End-to-end scenarios through the full Routine protocol (plan/verify/claim/save/send/save).

Tests 1-11 are the acceptance tests from the specification.
"""

from eve_sms.config import Settings
from eve_sms.providers import DryRunProvider, FakeProvider

from conftest import Routine, delivered, dispatched, order

NEW = "2026-10-01T10:30:00Z"  # created after the baseline run (10:00 UTC)


def start(routine, orders=()):
    r = routine.run(list(orders))
    assert r["claim"].baseline
    assert getattr(routine.provider, "calls", []) == []
    return r


def texts(routine):
    return [c["text"] for c in routine.provider.calls]


# ---- 1-11: specification acceptance tests -----------------------------------

def test_01_confirmed_order_sends_sms(routine):
    start(routine)
    r = routine.run([order(1001, status="confirmed", created=NEW, history=["pending", "confirmed"])])
    assert r["send"].sms_sent == 1
    call = routine.provider.calls[0]
    assert call["to"] == "+213555123456"
    assert "تأكد" in call["text"] and "2900 DA" in call["text"] and "@eve_worlld" in call["text"]
    assert routine.db.ledger()["1001:confirmed"]["r"] == "sent"
    log = routine.db.body("sms_log", "1001_confirmed")
    assert log["result"] == "sent" and log["attempt_count"] == 1 and log["total_price"] == 2900
    assert log["phone_number"] == "+213555123456" and log["customer_name"] == "Sara Test"


def test_02_same_status_again_sends_nothing(routine):
    start(routine)
    confirmed = [order(1001, status="confirmed", created=NEW)]
    routine.run(confirmed)
    for _ in range(3):
        r = routine.run(confirmed)
        assert r["planned"] == [] and r["send"] is None
    assert len(routine.provider.calls) == 1


def test_03_confirmed_then_delivery_desk_sends_second_sms(routine):
    start(routine)
    routine.run([order(1001, status="confirmed", created=NEW)])
    routine.run([dispatched(1001, "confirme_au_bureau", created=NEW)])
    assert len(routine.provider.calls) == 2
    assert "وصل لشركة التوصيل" in texts(routine)[1]


def test_04_delivery_desk_then_delivered_sends_third_sms(routine):
    start(routine)
    routine.run([order(1001, status="confirmed", created=NEW)])
    routine.run([dispatched(1001, "confirme_au_bureau", created=NEW)])
    routine.run([dispatched(1001, "vers_wilaya", tracking="in transit", created=NEW)])  # same stage: no SMS
    routine.run([delivered(1001, created=NEW)])
    assert len(routine.provider.calls) == 3
    assert "توصل بنجاح" in texts(routine)[2] and "المبلغ المدفوع: 2900 DA" in texts(routine)[2]
    ledger = routine.db.ledger()
    assert {k for k in ledger if k.startswith("1001:")} == {"1001:confirmed", "1001:delivery_desk", "1001:delivered"}


def test_05_cancelled_sends_cancellation_sms(routine):
    start(routine)
    routine.run([order(1002, status="pending", created=NEW)])
    r = routine.run([order(1002, status="canceled", created=NEW, history=["pending", "canceled"])])
    assert r["send"].sms_sent == 1
    assert "تلغى" in texts(routine)[0] and "DA" not in texts(routine)[0]


def test_06_returned_sends_returned_sms(routine):
    start(routine)
    routine.run([dispatched(1003, "sortie_en_livraison", tracking="out for delivery", created=NEW)])
    r = routine.run([order(1003, status="returned", source="returns", history=[], created=NEW)])
    assert r["send"].sms_sent == 1
    assert "رجع للمتجر" in texts(routine)[-1]


def test_07_invalid_phone_logged_and_other_orders_continue(routine):
    start(routine)
    r = routine.run([
        order(1004, status="confirmed", created=NEW, phone="12345"),
        order(1005, status="confirmed", created=NEW, phone="0661 22 33 44", name="Amina"),
    ])
    assert r["claim"].invalid_phones == 1
    assert [c["to"] for c in routine.provider.calls] == ["+213661223344"]
    entry = routine.db.ledger()["1004:confirmed"]
    assert entry["r"] == "invalid_phone" and "wrong length" in entry["why"]
    assert routine.db.body("sms_log", "1004_confirmed")["result"] == "invalid_phone"
    routine.run([order(1004, status="confirmed", created=NEW, phone="12345")])
    assert len(routine.provider.calls) == 1  # never retried automatically


def test_08_provider_failure_is_retried_automatically(tmp_path):
    routine = Routine(tmp_path, provider=FakeProvider(["HTTP 503: gateway busy", "ok"]))
    start(routine)
    r = routine.run([order(1006, status="confirmed", created=NEW)])
    assert [c["attempt"] for c in routine.provider.calls] == [1, 2]
    assert r["send"].sms_sent == 1 and r["send"].alerts == []
    assert routine.db.body("sms_log", "1006_confirmed")["attempt_count"] == 2


def test_09_two_failures_mark_failed_and_alert(tmp_path):
    routine = Routine(tmp_path, provider=FakeProvider(["insufficient balance", "insufficient balance"]))
    start(routine)
    r = routine.run([delivered(1007, created=NEW, name="Sara")])
    assert r["send"].sms_failed == 1 and len(routine.provider.calls) == 2
    alert = r["send"].alerts[0]
    assert alert["title"] == "⚠️ Eve World SMS failed"
    for part in ("Order: #00001007", "Customer: Sara", "Status: Delivered", "Phone: +213555123456",
                 "Attempts: 2", "Error: insufficient balance", "المبلغ المدفوع"):
        assert part in alert["body"]
    assert routine.db.ledger()["1007:delivered"]["r"] == "failed"
    assert routine.db.body("sms_log", "1007_delivered")["error"] == "insufficient balance"
    routine.run([delivered(1007, created=NEW, name="Sara")])
    assert len(routine.provider.calls) == 2  # no endless retries


def test_10_restart_keeps_history_and_sends_nothing_again(tmp_path):
    first = Routine(tmp_path / "a", )
    (tmp_path / "a").mkdir()
    start(first)
    orders = [order(1008, status="confirmed", created=NEW), delivered(1009, created=NEW)]
    first.run(orders)
    assert len(first.provider.calls) == 2
    # a brand-new process and provider, same saved database
    (tmp_path / "b").mkdir()
    restarted = Routine(tmp_path / "b", db=first.db)
    restarted.now = first.now
    for _ in range(2):
        r = restarted.run(orders)
        assert r["planned"] == []
    assert restarted.provider.calls == []


def test_11_first_run_is_a_silent_baseline(routine):
    existing = [
        order(1, status="confirmed"),
        dispatched(2, "confirme_au_bureau"),
        dispatched(3, "commande_recue"),
        delivered(4),
        order(5, status="canceled", history=["pending", "canceled"]),
        order(6, status="returned", source="returns", history=[]),
        order(7, status="pending"),
    ]
    r = start(routine, existing)
    assert r["claim"].orders_checked == 7
    assert routine.db.body("sms", "meta")["baseline_at"] == "2026-10-01T10:00:00Z"
    assert routine.run(existing)["planned"] == []
    assert routine.provider.calls == []
    # only a NEW transition after the baseline produces an SMS
    existing[1] = delivered(2)
    routine.run(existing)
    assert len(routine.provider.calls) == 1 and "توصل بنجاح" in texts(routine)[0]


# ---- behaviour found in the real account ------------------------------------

def test_confirm_and_dispatch_between_runs_still_sends_confirmed(routine):
    """Tassyir confirms and dispatches within seconds; the hourly run first sees commande_recue."""
    start(routine, [order(1010, status="pending")])
    routine.run([dispatched(1010, "commande_recue")])
    assert len(routine.provider.calls) == 1 and "تأكد" in texts(routine)[0]
    routine.run([dispatched(1010, "confirme_au_bureau")])
    assert len(routine.provider.calls) == 2 and "وصل لشركة التوصيل" in texts(routine)[1]


def test_skipping_stages_sends_only_the_current_one(routine):
    start(routine, [order(1011, status="pending")])
    routine.run([dispatched(1011, "vers_wilaya", tracking="in transit")])
    assert len(routine.provider.calls) == 1 and "وصل لشركة التوصيل" in texts(routine)[0]


def test_never_goes_back_to_an_earlier_stage(routine):
    start(routine)
    routine.run([dispatched(1012, "confirme_au_bureau", created=NEW)])
    r = routine.run([dispatched(1012, "commande_recue", created=NEW)])
    assert len(routine.provider.calls) == 1
    assert routine.db.ledger()["1012:confirmed"]["r"] == "skipped"
    assert r["claim"].skipped == 1


def test_abandoned_checkout_cancellation_is_not_texted(routine):
    start(routine)
    routine.run([order(1013, status="canceled", created=NEW, history=["abandoned", "test", "canceled"])])
    assert routine.provider.calls == []
    assert "abandoned" in routine.db.ledger()["1013:cancelled"]["why"]


def test_spam_or_banned_orders_are_not_texted(routine):
    start(routine)
    routine.run([order(1014, status="canceled", created=NEW, spam=True, history=["pending", "canceled"]),
                 order(1015, status="confirmed", created=NEW, banned=True)])
    assert routine.provider.calls == []


def test_price_is_the_tassyir_total_including_delivery(routine):
    start(routine)
    routine.run([order(1016, status="confirmed", created=NEW, total=3450)])  # 2700 item + 750 delivery
    assert "المبلغ الإجمالي: 3450 DA" in texts(routine)[0]


def test_customer_without_name_gets_plain_greeting(routine):
    start(routine)
    routine.run([order(1017, status="confirmed", created=NEW, name="  ")])
    assert texts(routine)[0].startswith("Salam\n")


def test_mismatch_between_reads_blocks_sms_until_they_agree(routine):
    start(routine)
    o = [order(1018, status="confirmed", created=NEW)]
    r = routine.run(o, verify_overrides={"1018": {"phone": "0555123457"}})
    assert routine.provider.calls == [] and r["claim"].verification_mismatches
    assert any("mismatch" in a["title"] for a in r["claim"].alerts)
    routine.run(o)
    assert len(routine.provider.calls) == 1


def test_failed_claim_save_sends_nothing_and_next_run_sends_once(routine):
    start(routine)
    o = [order(1019, status="confirmed", created=NEW)]
    r = routine.run(o, fail_claim_save=True)
    assert r["saved_claim"] is False and routine.provider.calls == []
    routine.run(o)
    routine.run(o)
    assert len(routine.provider.calls) == 1


def test_failed_result_save_never_causes_a_duplicate(routine):
    start(routine)
    o = [order(1020, status="confirmed", created=NEW)]
    r = routine.run(o, fail_send_save=True)
    assert r["saved_send"] is False and len(routine.provider.calls) == 1
    r = routine.run(o)
    assert len(routine.provider.calls) == 1
    assert routine.db.ledger()["1020:confirmed"]["r"] == "unconfirmed"
    assert r["claim"].alerts[0]["title"] == "⚠️ Eve World SMS unconfirmed"


def test_run_stopped_after_claim_is_flagged_not_resent(routine):
    start(routine)
    o = [order(1021, status="confirmed", created=NEW)]
    routine.run(o, skip_send=True)
    r = routine.run(o)
    assert routine.provider.calls == []
    assert routine.db.ledger()["1021:confirmed"]["r"] == "unconfirmed"
    assert any(a["title"] == "⚠️ Eve World SMS unconfirmed" for a in r["claim"].alerts)


def test_test_mode_sends_everything_to_the_owner_phone(tmp_path):
    routine = Routine(tmp_path, settings=Settings(mode="test", provider="fake", test_phone="0661234567",
                                                  retry_delay=0))
    start(routine)
    routine.run([order(1022, status="confirmed", created=NEW)])
    assert routine.provider.calls[0]["to"] == "+213661234567"
    assert routine.db.ledger()["1022:confirmed"]["r"] == "test_sent"
    assert routine.db.body("sms_log", "1022_confirmed")["phone_number"] == "+213555123456"


def test_dry_run_records_but_sends_nothing_and_going_live_does_not_replay(tmp_path):
    dry = Routine(tmp_path, settings=Settings(mode="dry_run", provider="dryrun"), provider=DryRunProvider())
    start(dry)
    o = [order(1023, status="confirmed", created=NEW)]
    dry.run(o)
    assert dry.db.ledger()["1023:confirmed"]["r"] == "dry_run"
    live = Routine(tmp_path / "live", db=dry.db)
    (tmp_path / "live").mkdir()
    live.now = dry.now
    live.run(o)
    assert live.provider.calls == []


def test_per_run_cap_defers_the_rest_to_next_hour(tmp_path):
    routine = Routine(tmp_path, settings=Settings(mode="live", provider="fake", max_per_run=3, retry_delay=0))
    start(routine)
    many = [order(2000 + i, status="confirmed", created=NEW, phone=f"055512{i:04d}") for i in range(5)]
    r = routine.run(many)
    assert len(routine.provider.calls) == 3 and r["claim"].deferred == 2
    routine.run(many)
    assert len(routine.provider.calls) == 5
    assert len({c["to"] for c in routine.provider.calls}) == 5


def test_unknown_carrier_status_is_reported_not_guessed(routine):
    start(routine)
    r = routine.run([dispatched(1024, "retour_en_cours", tracking="returning", created=NEW)])
    assert routine.provider.calls == []
    assert "dispatched/returning/retour_en_cours" in r["claim"].unknown_statuses


def test_one_malformed_order_does_not_stop_the_others(routine):
    start(routine)
    r = routine.run([order(1025, status="confirmed", created="not-a-date"),
                     order(1026, status="confirmed", created=NEW)])
    assert len(routine.provider.calls) == 1 and r["claim"].errors


def test_incomplete_first_read_postpones_the_baseline(routine):
    r = routine.run([order(1, status="confirmed")], complete=False, errors=["list_returns: timeout"])
    assert routine.db.body("sms", "meta") is None
    assert r["claim"].api_errors == 1 and r["claim"].alerts
    r = routine.run([order(1, status="confirmed")])
    assert r["claim"].baseline and routine.provider.calls == []


def test_queued_sms_is_reconciled_on_the_next_run(tmp_path):
    provider = FakeProvider(["queued"])
    routine = Routine(tmp_path, provider=provider)
    start(routine)
    o = [order(1027, status="confirmed", created=NEW)]
    routine.run(o)
    assert routine.db.ledger()["1027:confirmed"]["r"] == "queued"
    pmid = routine.db.ledger()["1027:confirmed"]["p"]
    provider.states[pmid] = "Failed"
    r = routine.run(o)
    assert routine.db.ledger()["1027:confirmed"]["r"] == "failed"
    assert r["claim"].alerts and len(provider.calls) == 1
