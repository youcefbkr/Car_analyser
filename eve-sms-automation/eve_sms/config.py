"""Settings, read from environment variables (never from source code)."""

import os
from dataclasses import dataclass

from .phone import InvalidPhone, normalize_dz_phone

MODES = ("dry_run", "test", "live")


class ConfigError(ValueError):
    pass


@dataclass
class Settings:
    mode: str = "dry_run"  # dry_run: no SMS; test: all SMS go to test_phone; live
    provider: str = "dryrun"
    test_phone: str = None
    template_set: str = "compact"
    max_per_run: int = 10  # Android allows ~30 SMS parts per 30 min per app
    max_attempts: int = 2
    retry_delay: float = 30.0
    retention_months: int = 3  # orders older than this are ignored


def from_env(env=None):
    env = os.environ if env is None else env
    mode = (env.get("EVE_SMS_MODE") or "dry_run").strip().lower()
    if mode not in MODES:
        raise ConfigError(f"EVE_SMS_MODE must be one of {', '.join(MODES)}")
    provider = (env.get("EVE_SMS_PROVIDER") or ("dryrun" if mode == "dry_run" else "smsgate")).strip().lower()
    if mode == "dry_run":
        provider = "dryrun"
    settings = Settings(
        mode=mode,
        provider=provider,
        test_phone=(env.get("EVE_SMS_TEST_PHONE") or "").strip() or None,
        template_set=(env.get("EVE_SMS_TEMPLATES") or "compact").strip().lower(),
        max_per_run=int(env.get("EVE_SMS_MAX_PER_RUN") or 10),
        max_attempts=int(env.get("EVE_SMS_MAX_ATTEMPTS") or 2),
        retry_delay=float(env.get("EVE_SMS_RETRY_DELAY_SECONDS") or 30),
        retention_months=int(env.get("EVE_SMS_RETENTION_MONTHS") or 3),
    )
    if settings.mode == "test" and not settings.test_phone:
        raise ConfigError("EVE_SMS_MODE=test needs EVE_SMS_TEST_PHONE (your own number)")
    if settings.test_phone:
        try:
            settings.test_phone = normalize_dz_phone(settings.test_phone)
        except InvalidPhone as exc:
            raise ConfigError(f"EVE_SMS_TEST_PHONE is not usable: {exc}")
    if settings.mode == "live" and settings.provider == "dryrun":
        raise ConfigError("EVE_SMS_MODE=live needs a real EVE_SMS_PROVIDER")
    if settings.max_attempts < 1 or settings.max_per_run < 1:
        raise ConfigError("EVE_SMS_MAX_ATTEMPTS and EVE_SMS_MAX_PER_RUN must be at least 1")
    return settings
