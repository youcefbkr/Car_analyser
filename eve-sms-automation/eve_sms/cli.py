"""Command line entry points used by the hourly Routine.

  python -m eve_sms plan  --db DIR --snapshot FILE
  python -m eve_sms claim --db DIR --snapshot FILE --verify-dir DIR --out DIR
  python -m eve_sms send  --db DIR --out DIR
  python -m eve_sms preview
  python -m eve_sms check-phone NUMBER

Every command prints one JSON object. `writes` points at the writes.json to
pass to one ArtifactData batch; `push` holds short alert lines for Claude
notifications.
"""

import argparse
import json
import sys

from . import config, templates
from .engine import Engine
from .phone import InvalidPhone, normalize_dz_phone
from .providers import ProviderError, build_provider
from .snapshot import SnapshotError, load_snapshot, load_verifications
from .store import Store, StoreError


def _load_store(args):
    versions = None
    if getattr(args, "versions", None):
        with open(args.versions, encoding="utf-8") as fh:
            versions = json.load(fh)
    return Store.load(args.db, versions)


def _push_lines(alerts):
    lines = []
    for a in alerts:
        body = " · ".join(line.strip() for line in (a.get("body") or "").splitlines()[:6] if line.strip())
        text = f"{a.get('title')}: {body}" if body else a.get("title")
        lines.append(text if len(text) <= 190 else text[:189] + "…")
    return lines


def _emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


def cmd_plan(args):
    settings = config.from_env()
    store = _load_store(args)
    snapshot = load_snapshot(args.snapshot)
    engine = Engine(store, settings)
    verify = engine.plan(snapshot)
    s = engine.summary
    _emit({
        "baseline_needed": s.baseline,
        "verify": verify,
        "deferred": s.deferred,
        "orders_checked": s.orders_checked,
        "unknown_statuses": s.unknown_statuses,
        "errors": s.errors,
    })


def cmd_claim(args):
    settings = config.from_env()
    store = _load_store(args)
    snapshot = load_snapshot(args.snapshot)
    verifications, problems = load_verifications(args.verify_dir)
    engine = Engine(store, settings, provider=build_provider(settings.provider))
    engine.summary.errors.extend(problems)
    pending = engine.claim(snapshot, verifications)
    writes = store.write_out(args.out)
    s = engine.summary
    _emit({
        "next": "save_then_send" if pending else "save_then_done",
        "writes": f"{args.out}/writes.json",
        "write_count": len(writes),
        "sms_to_send": len(pending),
        "summary": s.to_dict(),
        "push": _push_lines(s.alerts),
    })


def cmd_send(args):
    settings = config.from_env()
    store = _load_store(args)
    engine = Engine(store, settings, provider=build_provider(settings.provider))
    engine.send()
    writes = store.write_out(args.out)
    s = engine.summary
    _emit({
        "next": "save_then_done",
        "writes": f"{args.out}/writes.json",
        "write_count": len(writes),
        "summary": s.to_dict(),
        "push": _push_lines(s.alerts),
    })


def cmd_preview(args):
    for status in templates.TEMPLATES[args.templates]:
        text = templates.render(status, "Sara", 2900, args.templates)
        enc, units, segs = templates.segment_info(text)
        print(f"--- {status}  ({enc}, {units} units, {segs} SMS) ---\n{text}\n")


def cmd_check_phone(args):
    try:
        _emit({"input": args.number, "normalized": normalize_dz_phone(args.number)})
    except InvalidPhone as exc:
        _emit({"input": args.number, "invalid": str(exc)})


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eve_sms", description="Eve World Tassyir -> SMS automation")
    sub = parser.add_subparsers(dest="command", required=True)

    def db_args(p):
        p.add_argument("--db", action="append", required=True,
                       help="directory written by ArtifactData query out_dir (repeatable)")
        p.add_argument("--versions", help="JSON {\"sms/meta\": N, ...} to override stored versions")

    p = sub.add_parser("plan", help="list orders that need a get_order re-read")
    db_args(p)
    p.add_argument("--snapshot", required=True)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("claim", help="record status changes and claim SMS to send")
    db_args(p)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--verify-dir")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("send", help="send the saved claims")
    db_args(p)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("preview", help="print every template with its SMS segment count")
    p.add_argument("--templates", default="compact", choices=sorted(templates.TEMPLATES))
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("check-phone", help="normalize one phone number")
    p.add_argument("number")
    p.set_defaults(func=cmd_check_phone)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (SnapshotError, StoreError, ProviderError, config.ConfigError) as exc:
        _emit({"error": f"{type(exc).__name__}: {exc}"})
        return 2
    return 0
