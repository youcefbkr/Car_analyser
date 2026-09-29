"""SMS templates (Algerian Darija) and SMS segment accounting.

Arabic text forces UCS-2 encoding: 70 UTF-16 units fit in one SMS, and a
longer message is split into 67-unit segments, each billed as one SMS.
Emojis cost 2 units each. The "compact" set keeps every message at or under
2 segments (134 units) even with a 20-character name; "full" is the
original wording, which runs to 3 segments.
"""

import math
import re

from . import statuses as st

INSTAGRAM = "@eve_worlld"
STORE = "Eve World"
MAX_NAME_CHARS = 20

TEMPLATES = {
    "full": {
        st.CONFIRMED: (
            "Salam {name} 👋\n"
            "طلبك من Eve World تأكد بنجاح ✅\n"
            "💰 المبلغ الإجمالي: {total} DA\n"
            "راح نعلموك بكل جديد على طلبك.\n"
            "📱 Instagram: @eve_worlld"
        ),
        st.DELIVERY_DESK: (
            "Salam {name} 👋\n"
            "طلبك من Eve World راه وصل لشركة التوصيل 📦\n"
            "💰 المبلغ الإجمالي: {total} DA\n"
            "راح يتم التواصل معاك عند التوصيل.\n"
            "📱 @eve_worlld"
        ),
        st.DELIVERED: (
            "Salam {name} 🎀\n"
            "طلبك من Eve World تم توصيله بنجاح ✅\n"
            "💰 المبلغ المدفوع: {total} DA\n"
            "شكراً على ثقتك فينا 🤍\n"
            "📱 @eve_worlld"
        ),
        st.CANCELLED: (
            "Salam {name} 👋\n"
            "نعلموك بلي طلبك من Eve World تم إلغاؤه.\n"
            "إذا حبيتي أي مساعدة تواصلي معانا.\n"
            "📱 @eve_worlld"
        ),
        st.RETURNED: (
            "Salam {name} 👋\n"
            "نعلموك بلي طلبك من Eve World رجع للمتجر 📦\n"
            "إذا حبيتي نعاودو نتواصلو معاك بخصوص الطلب، راسلينا.\n"
            "📱 @eve_worlld"
        ),
    },
    "compact": {
        st.CONFIRMED: (
            "Salam {name}\n"
            "طلبك من Eve World تأكد ✅\n"
            "المبلغ الإجمالي: {total} DA\n"
            "راح نعلموك بكل جديد.\n"
            "Instagram: @eve_worlld"
        ),
        st.DELIVERY_DESK: (
            "Salam {name}\n"
            "طلبك من Eve World وصل لشركة التوصيل 📦\n"
            "المبلغ الإجمالي: {total} DA\n"
            "راح يتصلو بيك عند التوصيل.\n"
            "@eve_worlld"
        ),
        st.DELIVERED: (
            "Salam {name}\n"
            "طلبك من Eve World توصل بنجاح ✅\n"
            "المبلغ المدفوع: {total} DA\n"
            "شكراً على ثقتك فينا 🤍\n"
            "@eve_worlld"
        ),
        st.CANCELLED: (
            "Salam {name}\n"
            "نعلموك بلي طلبك من Eve World تلغى.\n"
            "إذا حبيتي مساعدة تواصلي معانا.\n"
            "Instagram: @eve_worlld"
        ),
        st.RETURNED: (
            "Salam {name}\n"
            "طلبك من Eve World رجع للمتجر 📦\n"
            "إذا حبيتي نتواصلو معاك على الطلب، راسلينا.\n"
            "Instagram: @eve_worlld"
        ),
    },
}

NEEDS_TOTAL = {st.CONFIRMED, st.DELIVERY_DESK, st.DELIVERED}

# GSM 03.38 basic set (+ extension chars which cost 2 septets).
_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXT = set("^{}\\[~]|€")


class TemplateError(ValueError):
    pass


def clean_name(name):
    name = re.sub(r"\s+", " ", (name or "")).strip()
    if len(name) > MAX_NAME_CHARS:
        name = name[:MAX_NAME_CHARS].rstrip()
    return name


def format_total(total):
    if total is None or isinstance(total, bool):
        raise TemplateError("order total is missing")
    try:
        value = float(total)
    except (TypeError, ValueError):
        raise TemplateError(f"order total is not a number: {total!r}")
    if value <= 0 or not math.isfinite(value):
        raise TemplateError(f"order total is not positive: {total!r}")
    return str(int(round(value)))


def render(status, name, total, template_set="compact"):
    try:
        template = TEMPLATES[template_set][status]
    except KeyError:
        raise TemplateError(f"no template for {template_set}/{status}")
    total_text = format_total(total) if status in NEEDS_TOTAL else ""
    customer = clean_name(name)
    text = template.format(name=customer, total=total_text)
    if not customer:
        # "Salam \n" -> "Salam\n" when Tassyir has no name for the customer.
        text = text.replace("Salam \n", "Salam\n", 1)
    return text


def segment_info(text):
    """Return (encoding, units, segments) as a carrier would bill it."""
    if all(c in _GSM_BASIC or c in _GSM_EXT for c in text):
        units = sum(2 if c in _GSM_EXT else 1 for c in text)
        return "GSM-7", units, 1 if units <= 160 else math.ceil(units / 153)
    units = len(text.encode("utf-16-le")) // 2
    return "UCS-2", units, 1 if units <= 70 else math.ceil(units / 67)
