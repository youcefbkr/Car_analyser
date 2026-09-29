"""SMS providers.

smsgate  "SMS Gateway for Android" (github.com/capcom6/android-sms-gateway):
         an Android phone with the store's SIM sends the SMS; its free cloud
         relay exposes an HTTP API. Credentials come from the app's
         "Cloud server" screen and are read from environment variables.
dryrun   sends nothing; used until a real provider is configured.
fake     scripted outcomes, for tests.
"""

import hashlib
import os
import time
from dataclasses import dataclass

import requests

# Message states reported by SMS Gateway for Android.
_ALIVE = {"Pending", "Processed", "Sent", "Delivered"}
_DONE_OK = {"Sent", "Delivered"}


@dataclass
class SendResult:
    ok: bool
    state: str = None  # "sent" | "delivered" | "queued" | "dry_run" | None
    provider_message_id: str = None
    error: str = None


class ProviderError(RuntimeError):
    pass


def message_id(key, attempt):
    """Stable per notification + attempt; lets a retry find the earlier attempt."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return f"eve-{digest}-{attempt}"


class DryRunProvider:
    name = "dryrun"

    def send(self, to, text, key, attempt):
        return SendResult(ok=True, state="dry_run", provider_message_id=None)

    def check(self, provider_message_id):
        return None


class FakeProvider:
    """outcomes: list consumed per send call; "ok", "queued" or an error string."""

    name = "fake"

    def __init__(self, outcomes=None, default="ok"):
        self.outcomes = list(outcomes or [])
        self.default = default
        self.calls = []
        self.states = {}

    def send(self, to, text, key, attempt):
        outcome = self.outcomes.pop(0) if self.outcomes else self.default
        pmid = message_id(key, attempt)
        self.calls.append({"to": to, "text": text, "key": key, "attempt": attempt, "outcome": outcome})
        if outcome == "ok":
            return SendResult(True, "sent", pmid)
        if outcome == "queued":
            self.states[pmid] = "Pending"
            return SendResult(True, "queued", pmid)
        return SendResult(False, None, None, outcome)

    def check(self, provider_message_id):
        return self.states.get(provider_message_id)


class SmsGateProvider:
    name = "smsgate"

    def __init__(self, username, password, base_url="https://api.sms-gate.app/3rdparty/v1",
                 ttl_seconds=21600, confirm_seconds=20, poll_every=4, timeout=20, session=None):
        if not username or not password:
            raise ProviderError("SMSGATE_USERNAME and SMSGATE_PASSWORD must be set")
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.ttl_seconds = ttl_seconds
        self.confirm_seconds = confirm_seconds
        self.poll_every = poll_every
        self.timeout = timeout
        self.http = session or requests.Session()
        self._path = None  # "messages" (current API) or "message" (older servers)

    def _url(self, suffix=""):
        return f"{self.base_url}/{self._path or 'messages'}{suffix}"

    def _post(self, body):
        resp = self.http.post(self._url(), json=body, auth=self.auth, timeout=self.timeout)
        if resp.status_code == 404 and self._path is None:
            self._path = "message"
            resp = self.http.post(self._url(), json=body, auth=self.auth, timeout=self.timeout)
        elif self._path is None:
            self._path = "messages"
        return resp

    def _state(self, pmid):
        """Return (state, error) for a message id, or (None, None) if unknown."""
        try:
            resp = self.http.get(self._url(f"/{pmid}"), auth=self.auth, timeout=self.timeout)
        except requests.RequestException:
            return None, None
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        errors = [r.get("error") for r in data.get("recipients") or [] if r.get("error")]
        return data.get("state"), "; ".join(errors) or None

    def check(self, provider_message_id):
        return self._state(provider_message_id)[0]

    def _settle(self, pmid, state):
        """Wait briefly for the phone to report; an unresolved message stays 'queued'."""
        deadline = time.monotonic() + self.confirm_seconds
        error = None
        while state not in _DONE_OK and state != "Failed" and time.monotonic() < deadline:
            time.sleep(self.poll_every)
            state, error = self._state(pmid)
        if state in _DONE_OK:
            return SendResult(True, state.lower(), pmid)
        if state == "Failed":
            return SendResult(False, None, pmid, f"phone reported Failed: {error or 'no reason given'}")
        return SendResult(True, "queued", pmid)

    def send(self, to, text, key, attempt):
        # Never send twice: if an earlier attempt is still alive, report it instead.
        for earlier in range(1, attempt):
            state, _ = self._state(message_id(key, earlier))
            if state in _ALIVE:
                return self._settle(message_id(key, earlier), state)

        pmid = message_id(key, attempt)
        body = {
            "id": pmid,
            "textMessage": {"text": text},
            "phoneNumbers": [to],
            "ttl": self.ttl_seconds,
            "withDeliveryReport": True,
        }
        try:
            resp = self._post(body)
        except requests.RequestException as exc:
            # The request may still have reached the server; look before giving up.
            state, _ = self._state(pmid)
            if state in _ALIVE:
                return self._settle(pmid, state)
            return SendResult(False, None, None, f"network error: {type(exc).__name__}")
        if resp.status_code == 409:
            state, _ = self._state(pmid)
            return self._settle(pmid, state)
        if resp.status_code >= 300:
            return SendResult(False, None, None, f"HTTP {resp.status_code}: {_short(resp.text)}")
        state = (resp.json() or {}).get("state") or "Pending"
        return self._settle(pmid, state)


def _short(text, limit=200):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def build_provider(name, env=None):
    env = os.environ if env is None else env
    if name == "dryrun":
        return DryRunProvider()
    if name == "smsgate":
        return SmsGateProvider(
            env.get("SMSGATE_USERNAME"),
            env.get("SMSGATE_PASSWORD"),
            base_url=env.get("SMSGATE_URL") or "https://api.sms-gate.app/3rdparty/v1",
            ttl_seconds=int(env.get("SMSGATE_TTL_SECONDS") or 21600),
        )
    raise ProviderError(f"unknown SMS provider {name!r} (use smsgate or dryrun)")
