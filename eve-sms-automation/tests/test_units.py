import json

import pytest

from eve_sms import statuses as st
from eve_sms.phone import InvalidPhone, mask_phone, normalize_dz_phone
from eve_sms.providers import SmsGateProvider, message_id
from eve_sms.snapshot import SnapshotError, parse_order, parse_snapshot, snapshot_from_raw
from eve_sms.templates import TEMPLATES, format_total, render, segment_info

from conftest import order


# ---- phone numbers -----------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "0555123456", "555123456", "+213555123456", "213555123456", "00213555123456",
    "+2130555123456", "0555 12 34 56", "0555-12-34-56", "(0555) 12.34.56", "٠٥٥٥١٢٣٤٥٦", " +213 555 123 456 ",
])
def test_phone_formats_normalize_to_e164(raw):
    assert normalize_dz_phone(raw) == "+213555123456"


@pytest.mark.parametrize("raw", ["0661223344", "0772129500"])
def test_all_three_operators(raw):
    assert normalize_dz_phone(raw).startswith("+2136") or normalize_dz_phone(raw).startswith("+2137")


@pytest.mark.parametrize("raw,reason", [
    (None, "missing"), ("", "missing"), ("12345", "wrong length"), ("021123456", "landline"),
    ("+33612345678", "not an Algerian"), ("0455123456", "not a mobile"), ("05551234567", "wrong length"),
    ("0555abc456", "unexpected characters"), ("+213555000000", "placeholder"),
])
def test_invalid_phones_are_rejected(raw, reason):
    with pytest.raises(InvalidPhone, match=reason):
        normalize_dz_phone(raw)


def test_never_produces_trunk_zero_after_country_code():
    for raw in ("0555123456", "+2130555123456", "002130555123456"):
        assert not normalize_dz_phone(raw).startswith("+2130")


def test_mask_phone():
    assert mask_phone("+213555123456") == "+213555***456"


# ---- templates -----------------------------------------------------------------

def test_compact_templates_never_exceed_two_sms_parts():
    for status in TEMPLATES["compact"]:
        text = render(status, "Abcdefghijklmnopqrstuvwxyz", 129900)
        assert segment_info(text) [2] <= 2, status


def test_every_template_mentions_store_and_instagram():
    for tset in TEMPLATES.values():
        for status in st.TARGET_STATUSES:
            text = render(status, "Sara", 2900, "full" if tset is TEMPLATES["full"] else "compact")
            assert "Eve World" in text and "@eve_worlld" in text


def test_total_formatting():
    assert format_total(2900) == "2900"
    assert format_total(2920.0) == "2920"
    for bad in (None, 0, -5, "abc", True):
        with pytest.raises(ValueError):
            format_total(bad)


def test_segment_counting():
    assert segment_info("Hello")[0] == "GSM-7"
    assert segment_info("a" * 161)[2] == 2
    assert segment_info("ب" * 70)[2] == 1
    assert segment_info("ب" * 71)[2] == 2


# ---- status mapping, with the combinations seen in the Eve World account ----------

@pytest.mark.parametrize("kwargs,expected", [
    (dict(status="pending"), None),
    (dict(status="scheduled"), None),
    (dict(status="abandoned"), None),
    (dict(status="test"), None),
    (dict(status="confirmed"), st.CONFIRMED),
    (dict(status="canceled"), st.CANCELLED),
    (dict(status="dispatched", source="tracking", tracking="to desk", carrier="commande_recue"), st.CONFIRMED),
    (dict(status="dispatched", source="tracking", tracking="to desk", carrier="confirme_au_bureau"), st.DELIVERY_DESK),
    (dict(status="dispatched", source="tracking", tracking="in transit", carrier="dispatch"), st.DELIVERY_DESK),
    (dict(status="dispatched", source="tracking", tracking="in transit", carrier="vers_wilaya"), st.DELIVERY_DESK),
    (dict(status="dispatched", source="tracking", tracking="out for delivery", carrier="sortie_en_livraison"),
     st.DELIVERY_DESK),
    (dict(status="delivered", source="tracking", tracking="delivered", carrier="livre"), st.DELIVERED),
    (dict(status="delivered", source="tracking", tracking="delivered", carrier="encaisse"), st.DELIVERED),
    (dict(status="returned", source="returns"), st.RETURNED),
])
def test_status_mapping(kwargs, expected):
    snap = parse_order(order(1, **kwargs))
    assert st.map_status(snap) == (expected, True)


def test_unseen_status_is_unknown():
    assert st.map_status(parse_order(order(1, status="brand_new_status"))) == (None, False)
    unknown_carrier = parse_order(order(1, status="dispatched", source="tracking", tracking="to desk", carrier="xyz"))
    assert st.map_status(unknown_carrier) == (None, False)


# ---- snapshots -------------------------------------------------------------------

def test_raw_tassyir_items_convert_and_later_list_wins():
    raw_order = {"id": "9", "orderNumber": "#00000009", "createdAt": "2026-09-21T17:11:36.478Z",
                 "status": "confirmed", "total": 3370, "isSpam": False,
                 "statusHistory": [{"status": "confirmed"}, {"status": "pending"}],
                 "orderClient": {"name": "Test Client", "phone": "+213770000001", "isBanned": False}}
    raw_track = dict(raw_order, status="dispatched", trackingStatus="in transit", deliveryStatus="vers_wilaya")
    raw_track.pop("statusHistory")
    data = snapshot_from_raw("2026-09-29T16:00:00Z", [{"data": [raw_order]}], [{"data": [raw_track]}])
    snap = parse_snapshot(json.loads(json.dumps(data)))
    assert len(snap.orders) == 1
    o = snap.orders[0]
    assert (o.source, o.delivery_status, o.total) == ("tracking", "vers_wilaya", 3370)
    assert o.history == ["confirmed", "pending"]  # kept from the orders list


@pytest.mark.parametrize("field,value", [("total", True), ("total", "2900"), ("id", "abc"), ("source", "web"),
                                         ("is_spam", "no"), ("history", "pending")])
def test_malformed_snapshot_is_refused(field, value):
    bad = order(1, status="confirmed")
    bad[field] = value
    with pytest.raises(SnapshotError):
        parse_snapshot({"fetched_at": "2026-09-29T16:00:00Z", "complete": True, "errors": [], "orders": [bad]})


# ---- SMS Gateway for Android client -------------------------------------------------

class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, posts, states=None):
        self.posts = list(posts)
        self.states = states or {}
        self.sent = []

    def post(self, url, json=None, auth=None, timeout=None):
        self.sent.append((url, json))
        outcome = self.posts.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get(self, url, auth=None, timeout=None):
        pmid = url.rsplit("/", 1)[-1]
        state = self.states.get(pmid)
        return FakeResponse(200, {"state": state, "recipients": []}) if state else FakeResponse(404)


def gate(session):
    return SmsGateProvider("user", "pass", session=session, confirm_seconds=0, poll_every=0)


def test_smsgate_sends_expected_request():
    session = FakeSession([FakeResponse(202, {"id": "x", "state": "Pending"})])
    res = gate(session).send("+213555123456", "نص", "1:confirmed", 1)
    url, body = session.sent[0]
    assert url.endswith("/3rdparty/v1/messages")
    assert body["phoneNumbers"] == ["+213555123456"] and body["textMessage"] == {"text": "نص"}
    assert body["id"] == message_id("1:confirmed", 1) and len(body["id"]) <= 36
    assert res.ok and res.state == "queued"


def test_smsgate_falls_back_to_singular_path_on_404():
    session = FakeSession([FakeResponse(404), FakeResponse(202, {"state": "Sent"})])
    res = gate(session).send("+213555123456", "t", "1:confirmed", 1)
    assert session.sent[1][0].endswith("/3rdparty/v1/message") and res.ok and res.state == "sent"


def test_smsgate_http_error_is_a_failure():
    session = FakeSession([FakeResponse(401, {"message": "unauthorized"})])
    res = gate(session).send("+213555123456", "t", "1:confirmed", 1)
    assert not res.ok and "HTTP 401" in res.error


def test_smsgate_retry_does_not_resend_when_first_attempt_is_alive():
    first = message_id("1:confirmed", 1)
    session = FakeSession([], states={first: "Sent"})
    res = gate(session).send("+213555123456", "t", "1:confirmed", 2)
    assert session.sent == [] and res.ok and res.provider_message_id == first


def test_smsgate_lost_response_is_detected_not_resent():
    import requests
    pmid = message_id("1:confirmed", 1)
    session = FakeSession([requests.Timeout("read timeout")], states={pmid: "Pending"})
    res = gate(session).send("+213555123456", "t", "1:confirmed", 1)
    assert res.ok and res.provider_message_id == pmid and len(session.sent) == 1
