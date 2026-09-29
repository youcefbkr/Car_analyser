"""Order snapshots: what one hourly run saw in Tassyir.

The hourly Routine reads Tassyir through Claude's Tassyir connector and
writes a compact snapshot file (schema below). Everything is validated
strictly: a malformed file aborts the run instead of producing wrong SMS.

snapshot.json
{
  "fetched_at": "2026-09-29T16:00:00Z",
  "complete": true,            # false if any Tassyir call failed
  "errors": [],                # the failed calls, as text
  "orders": [ {ORDER}, ... ]
}
ORDER
{
  "id": "760042562714079883", "number": "#00000029",
  "created_at": "2026-09-29T07:37:47.855Z",
  "source": "orders" | "tracking" | "returns",
  "status": "confirmed",       # order-level status
  "tracking_status": null,     # trackingStatus (tracking source)
  "delivery_status": null,     # deliveryStatus, carrier code (tracking source)
  "history": ["pending", "confirmed"],   # statusHistory[].status, any order
  "name": "...", "phone": "+213...", "total": 3450,
  "is_spam": false, "is_banned": false
}

verify/<order id>.json (a second, independent read with get_order, made only
for orders about to receive an SMS)
{"id": "...", "number": "#...", "status": "dispatched",
 "name": "...", "phone": "+213...", "total": 2920}
"""

import json
import os
from dataclasses import dataclass, field

SOURCES = ("orders", "tracking", "returns")
_PRECEDENCE = {"orders": 0, "tracking": 1, "returns": 2}


class SnapshotError(ValueError):
    pass


@dataclass
class OrderSnapshot:
    id: str
    number: str
    created_at: str
    source: str
    status: str
    tracking_status: str = None
    delivery_status: str = None
    history: list = field(default_factory=list)
    name: str = ""
    phone: str = None
    total: float = None
    is_spam: bool = False
    is_banned: bool = False


@dataclass
class Snapshot:
    fetched_at: str
    complete: bool
    errors: list
    orders: list  # of OrderSnapshot, one per order id


@dataclass
class Verification:
    id: str
    number: str
    status: str
    name: str
    phone: str
    total: float


def _require(obj, key, types, where, nullable=False):
    if key not in obj:
        raise SnapshotError(f"{where}: missing field {key!r}")
    value = obj[key]
    if value is None and nullable:
        return None
    types = types if isinstance(types, tuple) else (types,)
    # bool is a subclass of int in Python; never accept True as a price.
    wrong_bool = isinstance(value, bool) and bool not in types
    if wrong_bool or not isinstance(value, types):
        raise SnapshotError(f"{where}: field {key!r} has wrong type {type(value).__name__}")
    return value


def parse_order(obj, index=0):
    where = f"orders[{index}]"
    if not isinstance(obj, dict):
        raise SnapshotError(f"{where}: not an object")
    order_id = _require(obj, "id", str, where)
    if not order_id.isdigit():
        raise SnapshotError(f"{where}: id {order_id!r} is not a Tassyir id")
    source = _require(obj, "source", str, where)
    if source not in SOURCES:
        raise SnapshotError(f"{where}: unknown source {source!r}")
    history = _require(obj, "history", list, where)
    if not all(isinstance(h, str) for h in history):
        raise SnapshotError(f"{where}: history must be a list of strings")
    return OrderSnapshot(
        id=order_id,
        number=_require(obj, "number", str, where),
        created_at=_require(obj, "created_at", str, where),
        source=source,
        status=_require(obj, "status", str, where),
        tracking_status=_require(obj, "tracking_status", str, where, nullable=True),
        delivery_status=_require(obj, "delivery_status", str, where, nullable=True),
        history=history,
        name=_require(obj, "name", str, where, nullable=True) or "",
        phone=_require(obj, "phone", str, where, nullable=True),
        total=_require(obj, "total", (int, float), where, nullable=True),
        is_spam=_require(obj, "is_spam", bool, where),
        is_banned=_require(obj, "is_banned", bool, where),
    )


def parse_snapshot(data):
    if not isinstance(data, dict):
        raise SnapshotError("snapshot is not a JSON object")
    fetched_at = _require(data, "fetched_at", str, "snapshot")
    complete = _require(data, "complete", bool, "snapshot")
    errors = _require(data, "errors", list, "snapshot")
    raw_orders = _require(data, "orders", list, "snapshot")
    merged = {}
    for i, raw in enumerate(raw_orders):
        order = parse_order(raw, i)
        current = merged.get(order.id)
        # An order can show up in several lists while it moves; the later
        # lifecycle list (returns > tracking > orders) is the truth.
        if current is None or _PRECEDENCE[order.source] >= _PRECEDENCE[current.source]:
            if current and not order.history:
                order.history = current.history
            merged[order.id] = order
    return Snapshot(fetched_at, complete, [str(e) for e in errors], list(merged.values()))


def load_snapshot(path):
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"{path} is not valid JSON: {exc}")
    return parse_snapshot(data)


def parse_verification(data, where="verify"):
    if not isinstance(data, dict):
        raise SnapshotError(f"{where}: not an object")
    return Verification(
        id=_require(data, "id", str, where),
        number=_require(data, "number", str, where),
        status=_require(data, "status", str, where),
        name=_require(data, "name", str, where, nullable=True) or "",
        phone=_require(data, "phone", str, where, nullable=True),
        total=_require(data, "total", (int, float), where, nullable=True),
    )


def load_verifications(directory):
    """Return ({order_id: Verification}, [problems])."""
    found, problems = {}, []
    if not directory or not os.path.isdir(directory):
        return found, problems
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                v = parse_verification(json.load(fh), where=name)
            if v.id != name[:-5]:
                raise SnapshotError(f"{name}: id inside file is {v.id}")
            found[v.id] = v
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    return found, problems


# --- conversion from raw Tassyir tool responses (tests, manual runs) --------

def _history_statuses(item):
    out = []
    for h in item.get("statusHistory") or []:
        if isinstance(h, dict) and isinstance(h.get("status"), str):
            out.append(h["status"])
    return out


def compact_from_raw(item, source):
    """Turn one item of list_orders / list_order_tracking / list_returns into ORDER."""
    client = item.get("orderClient") or {}
    return {
        "id": str(item["id"]),
        "number": item.get("orderNumber") or "",
        "created_at": item.get("createdAt") or "",
        "source": source,
        "status": item.get("status") or "",
        "tracking_status": item.get("trackingStatus"),
        "delivery_status": item.get("deliveryStatus"),
        "history": _history_statuses(item),
        "name": client.get("name") or "",
        "phone": client.get("phone"),
        "total": item.get("total"),
        "is_spam": bool(item.get("isSpam")),
        "is_banned": bool(client.get("isBanned")),
    }


def snapshot_from_raw(fetched_at, orders_pages=(), tracking_pages=(), returns_pages=(), errors=()):
    items = []
    for source, pages in (("orders", orders_pages), ("tracking", tracking_pages), ("returns", returns_pages)):
        for page in pages:
            for item in page.get("data") or []:
                items.append(compact_from_raw(item, source))
    return {"fetched_at": fetched_at, "complete": not errors, "errors": list(errors), "orders": items}


def verification_from_raw(item):
    client = item.get("orderClient") or {}
    return {
        "id": str(item["id"]),
        "number": item.get("orderNumber") or "",
        "status": item.get("status") or "",
        "name": client.get("name") or "",
        "phone": client.get("phone"),
        "total": item.get("total"),
    }
