"""Algerian phone number normalization and validation.

Every number that leaves this module is either a valid Algerian mobile in
E.164 form (+213 followed by 9 digits starting with 5, 6 or 7) or an
InvalidPhone error explaining why it was rejected.
"""

import re

COUNTRY_CODE = "213"
MOBILE_PREFIXES = ("5", "6", "7")  # Ooredoo, Mobilis, Djezzy
LANDLINE_PREFIXES = ("2", "3", "4")

# Customers sometimes type Arabic-Indic or Persian digits.
_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SEPARATORS = re.compile(r"[\s\-\.\(\)/‎‏‪-‮]")


class InvalidPhone(ValueError):
    """Raised when a number cannot safely receive an SMS."""


def normalize_dz_phone(raw):
    """Return the number as +213XXXXXXXXX or raise InvalidPhone.

    Accepted inputs include 0555123456, 555123456, 213555123456,
    +213555123456, 00213555123456 and the malformed +2130555123456.
    """
    if raw is None or not str(raw).strip():
        raise InvalidPhone("missing phone number")

    text = _SEPARATORS.sub("", str(raw).translate(_DIGIT_TRANSLATION))
    has_plus = text.startswith("+")
    digits = text[1:] if has_plus else text
    if not digits.isdigit():
        raise InvalidPhone(f"unexpected characters in {raw!r}")

    if digits.startswith("00"):
        digits = digits[2:]
        has_plus = True

    if has_plus or (digits.startswith(COUNTRY_CODE) and len(digits) in (11, 12, 13)):
        if not digits.startswith(COUNTRY_CODE):
            raise InvalidPhone(f"not an Algerian number: {raw!r}")
        national = digits[len(COUNTRY_CODE):]
    else:
        national = digits

    # Drop the trunk prefix: 0555123456 and +2130555123456 both carry it.
    if national.startswith("0"):
        national = national[1:]

    if len(national) == 8 and national.startswith(LANDLINE_PREFIXES):
        raise InvalidPhone(f"landline cannot receive SMS: {raw!r}")
    if len(national) != 9:
        raise InvalidPhone(f"wrong length ({len(national)} digits after +213): {raw!r}")
    if not national.startswith(MOBILE_PREFIXES):
        raise InvalidPhone(f"not a mobile number (must start 5/6/7): {raw!r}")
    if len(set(national[-6:])) == 1:
        raise InvalidPhone(f"placeholder-looking number: {raw!r}")

    return f"+{COUNTRY_CODE}{national}"


def mask_phone(e164):
    """+213555123456 -> +213555***456, for logs and alerts shown outside the DB."""
    if not e164 or len(e164) < 8:
        return e164 or ""
    return f"{e164[:7]}***{e164[-3:]}"
