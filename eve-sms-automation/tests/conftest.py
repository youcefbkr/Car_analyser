"""Test harness: a fake artifact database and a simulated hourly Routine.

FakeArtifactDB follows the real ArtifactData rules checked against the live
service on 2026-09-29: a batch is atomic, every write to an existing
document must be pinned to its current version, a pinned write to a stale
version refuses the whole batch, and each write bumps the version by one.
"""

import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eve_sms.config import Settings  # noqa: E402
from eve_sms.engine import Engine  # noqa: E402
from eve_sms.providers import FakeProvider  # noqa: E402
from eve_sms.snapshot import load_verifications, parse_snapshot  # noqa: E402
from eve_sms.store import Store  # noqa: E402

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


class VersionMismatch(Exception):
    pass


class FakeArtifactDB:
    def __init__(self):
        self.docs = {}  # (collection, doc_id) -> (version, body)
        self.fail_next_batch = False

    def query_active(self, out_dir):
        os.makedirs(os.path.join(out_dir, "sms"), exist_ok=True)
        for (collection, doc_id), (_, body) in self.docs.items():
            if collection == "sms" and body.get("active") is True:
                with open(os.path.join(out_dir, "sms", f"{doc_id}.json"), "w", encoding="utf-8") as fh:
                    json.dump(body, fh, ensure_ascii=False, indent=2)

    def batch(self, writes):
        if self.fail_next_batch:
            self.fail_next_batch = False
            raise ConnectionError("simulated save failure")
        staged = dict(self.docs)
        for w in writes:
            key = (w["collection"], w["doc_id"])
            current = staged.get(key)
            if current is not None:
                if "if_version" not in w:
                    raise VersionMismatch(f"{key} exists and write is not pinned")
                if w["if_version"] != current[0]:
                    raise VersionMismatch(f"{key} pinned to {w['if_version']} but is at {current[0]}")
            with open(w["file_path"], encoding="utf-8") as fh:
                body = json.load(fh)
            staged[key] = ((current[0] if current else 0) + 1, body)
        self.docs = staged

    def body(self, collection, doc_id):
        entry = self.docs.get((collection, doc_id))
        return copy.deepcopy(entry[1]) if entry else None

    def collection(self, collection):
        return {d: copy.deepcopy(b) for (c, d), (_, b) in self.docs.items() if c == collection}

    def ledger(self):
        out = {}
        for doc_id, body in self.collection("sms").items():
            if doc_id.startswith("m-"):
                out.update(body.get("ledger", {}))
        return out


def order(oid, *, status="pending", source="orders", tracking=None, carrier=None, history=None,
          name="Sara Test", phone="0555123456", total=2900, created="2026-10-01T08:00:00Z",
          number=None, spam=False, banned=False):
    return {
        "id": str(oid), "number": number or f"#{int(oid) % 100000:08d}", "created_at": created,
        "source": source, "status": status, "tracking_status": tracking, "delivery_status": carrier,
        "history": history if history is not None else ([status] if source == "orders" else []),
        "name": name, "phone": phone, "total": total, "is_spam": spam, "is_banned": banned,
    }


def dispatched(oid, carrier, tracking="to desk", **kw):
    return order(oid, status="dispatched", source="tracking", tracking=tracking, carrier=carrier, **kw)


def delivered(oid, **kw):
    return order(oid, status="delivered", source="tracking", tracking="delivered", carrier="livre", **kw)


class Routine:
    """Replays the hourly Routine protocol: read -> plan -> verify -> claim -> save -> (read -> send -> save)."""

    def __init__(self, tmp_path, db=None, settings=None, provider=None):
        self.tmp = tmp_path
        self.db = db or FakeArtifactDB()
        self.settings = settings or Settings(mode="live", provider="fake", retry_delay=0)
        self.provider = provider or FakeProvider()
        self.n = 0
        self.now = T0

    def run(self, orders, *, verify_overrides=None, complete=True, errors=(), skip_send=False,
            fail_claim_save=False, fail_send_save=False, advance=timedelta(hours=1)):
        self.n += 1
        self.now = self.now + advance
        work = self.tmp / f"run{self.n}"
        work.mkdir()
        snap_data = {"fetched_at": self.now.strftime("%Y-%m-%dT%H:%M:%SZ"), "complete": complete,
                     "errors": list(errors), "orders": orders}
        snapshot = parse_snapshot(copy.deepcopy(snap_data))

        # plan (read-only)
        self.db.query_active(str(work / "db"))
        store = Store.load([str(work / "db")])
        planned = Engine(store, self.settings, self.provider, now=self.now, sleep=lambda s: None).plan(snapshot)

        # independent get_order re-read of each planned order
        vdir = work / "verify"
        vdir.mkdir()
        by_id = {o["id"]: o for o in orders}
        for oid in planned:
            o = by_id[oid]
            v = {"id": oid, "number": o["number"], "status": o["status"], "name": o["name"],
                 "phone": o["phone"], "total": o["total"]}
            v.update((verify_overrides or {}).get(oid, {}))
            (vdir / f"{oid}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")

        # claim, then save
        self.db.query_active(str(work / "db1"))
        store = Store.load([str(work / "db1")])
        engine = Engine(store, self.settings, self.provider, now=self.now, sleep=lambda s: None)
        verifications, _ = load_verifications(str(vdir))
        pending = engine.claim(snapshot, verifications)
        writes = store.write_out(str(work / "out1"))
        result = {"planned": planned, "claim": engine.summary, "send": None, "saved_claim": True}
        if fail_claim_save:
            self.db.fail_next_batch = True
        try:
            self.db.batch(writes)
        except Exception:
            result["saved_claim"] = False
            return result  # the Routine stops: nothing is sent
        if not pending or skip_send:
            return result

        # send, then save
        self.db.query_active(str(work / "db2"))
        store = Store.load([str(work / "db2")])
        engine = Engine(store, self.settings, self.provider, now=self.now, sleep=lambda s: None)
        engine.send()
        writes = store.write_out(str(work / "out2"))
        result["send"] = engine.summary
        if fail_send_save:
            self.db.fail_next_batch = True
        try:
            self.db.batch(writes)
            result["saved_send"] = True
        except Exception:
            result["saved_send"] = False
        return result


@pytest.fixture
def routine(tmp_path):
    return Routine(tmp_path)
