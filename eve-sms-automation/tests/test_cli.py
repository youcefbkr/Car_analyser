"""Smoke test of the command line wiring the Routine uses."""

import json

from eve_sms.cli import main

from conftest import order


def run_cli(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_plan_and_claim_from_the_command_line(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("EVE_SMS_MODE", "dry_run")
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"fetched_at": "2026-09-29T16:00:00Z", "complete": True, "errors": [],
                                "orders": [order(1, status="confirmed", created="2026-09-29T08:00:00Z")]}))
    code, out = run_cli(capsys, "plan", "--db", str(tmp_path / "db"), "--snapshot", str(snap))
    assert code == 0 and out["baseline_needed"] is True and out["verify"] == []
    code, out = run_cli(capsys, "claim", "--db", str(tmp_path / "db"), "--snapshot", str(snap),
                        "--verify-dir", str(tmp_path / "verify"), "--out", str(tmp_path / "out"))
    assert code == 0 and out["next"] == "save_then_done" and out["summary"]["baseline"] is True
    writes = json.loads((tmp_path / "out" / "writes.json").read_text())
    assert {w["doc_id"] for w in writes} >= {"meta", "m-2026-09"}
    assert all("if_version" not in w for w in writes)  # new documents


def test_malformed_snapshot_exits_with_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("EVE_SMS_MODE", "dry_run")
    snap = tmp_path / "snapshot.json"
    snap.write_text('{"fetched_at": "x", "complete": true, "errors": [], "orders": [{"id": "1"}]}')
    code, out = run_cli(capsys, "plan", "--db", str(tmp_path / "db"), "--snapshot", str(snap))
    assert code == 2 and "SnapshotError" in out["error"]


def test_live_mode_without_credentials_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("EVE_SMS_MODE", "live")
    monkeypatch.delenv("SMSGATE_USERNAME", raising=False)
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"fetched_at": "2026-09-29T16:00:00Z", "complete": True, "errors": [], "orders": []}))
    code, out = run_cli(capsys, "claim", "--db", str(tmp_path / "db"), "--snapshot", str(snap),
                        "--out", str(tmp_path / "out"))
    assert code == 2 and "SMSGATE_USERNAME" in out["error"]
