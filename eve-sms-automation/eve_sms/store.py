"""Persistent state, kept as JSON documents in a private claude.ai artifact database.

Layout (collection/doc):
  sms/meta          baseline time, mode, pending sends, last run summary
  sms/m-YYYY-MM     orders created that month + the notification ledger for them
  sms_log/<key>     one full record per notification (write-once, for the log view)
  sms_runs/<run id> one summary per run (write-once)

Each run the Routine reads every `sms` doc with `active == true` into a
directory (ArtifactData query with out_dir), this module loads that
directory, and writes changed docs to an output directory together with
writes.json, the exact `writes` list for one atomic ArtifactData batch.

Document versions: the database bumps a document's version by one on every
write and refuses a write pinned to a stale version. Only this program writes
these documents, so each body carries `_rev` (its own write count), which is
exactly the version to pin. If anything else ever writes them, the batch is
refused as a whole and nothing is lost; pass --versions to resync.
"""

import json
import os
from datetime import datetime, timezone

SCHEMA = 1
COLLECTION = "sms"
LOG_COLLECTION = "sms_log"
RUNS_COLLECTION = "sms_runs"
MAX_DOC_BYTES = 250_000  # the database refuses documents over 256 KiB


class StoreError(RuntimeError):
    pass


def month_of(iso_ts):
    """'2026-09-29T07:37:47.855Z' -> '2026-09'."""
    if not isinstance(iso_ts, str) or len(iso_ts) < 7 or iso_ts[4] != "-":
        raise StoreError(f"bad timestamp {iso_ts!r}")
    return iso_ts[:7]


def ledger_key(order_id, status):
    return f"{order_id}:{status}"


class Store:
    def __init__(self):
        self.meta = None
        self.meta_rev = 0  # 0 = document does not exist yet
        self.months = {}  # "2026-09" -> doc body
        self.month_revs = {}
        self.dirty = set()  # doc ids in COLLECTION to write
        self.write_once = []  # (collection, doc_id, body)

    # ---- loading -------------------------------------------------------

    @classmethod
    def load(cls, db_dirs, versions=None):
        """Load every sms/*.json found under the given ArtifactData out_dirs."""
        store = cls()
        for base in db_dirs:
            folder = os.path.join(base, COLLECTION)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    body = json.load(fh)
                store._adopt(name[:-5], body)
        for doc_path, version in (versions or {}).items():
            collection, _, doc_id = doc_path.partition("/")
            if collection != COLLECTION:
                continue
            if doc_id == "meta" and store.meta is not None:
                store.meta_rev = int(version)
            elif doc_id.startswith("m-") and doc_id[2:] in store.months:
                store.month_revs[doc_id[2:]] = int(version)
        return store

    def _adopt(self, doc_id, body):
        if not isinstance(body, dict):
            raise StoreError(f"{COLLECTION}/{doc_id} is not an object")
        if body.get("schema", SCHEMA) != SCHEMA:
            raise StoreError(f"{COLLECTION}/{doc_id} has unsupported schema {body.get('schema')}")
        rev = body.get("_rev")
        if not isinstance(rev, int) or rev < 1:
            raise StoreError(f"{COLLECTION}/{doc_id} has no valid _rev")
        if doc_id == "meta":
            self.meta, self.meta_rev = body, rev
        elif doc_id.startswith("m-"):
            month = doc_id[2:]
            body.setdefault("orders", {})
            body.setdefault("ledger", {})
            self.months[month], self.month_revs[month] = body, rev

    # ---- meta ------------------------------------------------------------

    @property
    def has_baseline(self):
        return bool(self.meta and self.meta.get("baseline_at"))

    def ensure_meta(self):
        if self.meta is None:
            self.meta = {"kind": "meta", "active": True, "schema": SCHEMA, "baseline_at": None, "pending": []}
        self.dirty.add("meta")
        return self.meta

    # ---- month shards ------------------------------------------------------

    def _month(self, month, create):
        doc = self.months.get(month)
        if doc is None and create:
            doc = {"kind": "month", "active": True, "schema": SCHEMA, "month": month, "orders": {}, "ledger": {}}
            self.months[month] = doc
            self.month_revs[month] = 0
        return doc

    def get_order(self, order_id, created_at):
        doc = self._month(month_of(created_at), create=False)
        return doc["orders"].get(order_id) if doc else None

    def put_order(self, order_id, created_at, record):
        month = month_of(created_at)
        self._month(month, create=True)["orders"][order_id] = record
        self.dirty.add(f"m-{month}")

    def get_ledger(self, order_id, created_at, status):
        doc = self._month(month_of(created_at), create=False)
        return doc["ledger"].get(ledger_key(order_id, status)) if doc else None

    def put_ledger(self, order_id, created_at, status, entry):
        month = month_of(created_at)
        self._month(month, create=True)["ledger"][ledger_key(order_id, status)] = entry
        self.dirty.add(f"m-{month}")

    def ledger_for_order(self, order_id, created_at):
        doc = self._month(month_of(created_at), create=False)
        if not doc:
            return {}
        prefix = f"{order_id}:"
        return {k[len(prefix):]: v for k, v in doc["ledger"].items() if k.startswith(prefix)}

    def iter_ledger(self):
        for month, doc in self.months.items():
            for key, entry in doc["ledger"].items():
                order_id, _, status = key.partition(":")
                yield month, order_id, status, entry

    def touch_month(self, month):
        self.dirty.add(f"m-{month}")

    def deactivate_months_before(self, first_active_month):
        for month, doc in self.months.items():
            if month < first_active_month and doc.get("active"):
                doc["active"] = False
                self.dirty.add(f"m-{month}")

    # ---- write-once docs ---------------------------------------------------

    def add_log(self, doc_id, body):
        self.write_once.append((LOG_COLLECTION, doc_id, body))

    def add_run(self, doc_id, body):
        self.write_once.append((RUNS_COLLECTION, doc_id, body))

    # ---- output ------------------------------------------------------------

    def write_out(self, out_dir):
        """Write changed documents under out_dir and return the batch `writes` list."""
        os.makedirs(out_dir, exist_ok=True)
        writes = []
        for doc_id in sorted(self.dirty):
            if doc_id == "meta":
                body, rev = self.meta, self.meta_rev
            else:
                month = doc_id[2:]
                body, rev = self.months[month], self.month_revs[month]
            body["_rev"] = rev + 1
            body["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            path = _dump(out_dir, COLLECTION, doc_id, body)
            entry = {"op": "set", "collection": COLLECTION, "doc_id": doc_id, "file_path": path}
            if rev:
                entry["if_version"] = rev
            writes.append(entry)
        for collection, doc_id, body in self.write_once:
            path = _dump(out_dir, collection, doc_id, body)
            writes.append({"op": "set", "collection": collection, "doc_id": doc_id, "file_path": path})
        if len(writes) > 50:
            raise StoreError(f"{len(writes)} writes exceed one batch (50); run again to spread them")
        with open(os.path.join(out_dir, "writes.json"), "w", encoding="utf-8") as fh:
            json.dump(writes, fh, ensure_ascii=False, indent=1)
        return writes


def _dump(out_dir, collection, doc_id, body):
    folder = os.path.join(out_dir, collection)
    os.makedirs(folder, exist_ok=True)
    path = os.path.abspath(os.path.join(folder, f"{doc_id}.json"))
    data = json.dumps(body, ensure_ascii=False, sort_keys=True)
    if len(data.encode("utf-8")) > MAX_DOC_BYTES:
        raise StoreError(f"{collection}/{doc_id} would exceed the 256 KiB document limit")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return path
