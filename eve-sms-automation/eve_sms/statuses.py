"""Tassyir status -> automation status mapping.

Values below were read from the Eve World Tassyir account on 2026-09-29
(orders use ZR Express as the delivery company). Edit the sets here if
Tassyir or the carrier introduces new values; unknown values are never
guessed, they are reported in the run summary instead.
"""

CONFIRMED = "confirmed"
DELIVERY_DESK = "delivery_desk"
DELIVERED = "delivered"
CANCELLED = "cancelled"
RETURNED = "returned"

TARGET_STATUSES = (CONFIRMED, DELIVERY_DESK, DELIVERED, CANCELLED, RETURNED)

# Forward path of a healthy order. Used to avoid sending an older-stage SMS
# after a newer-stage one (e.g. "confirmed" after "delivered to desk").
FORWARD_RANK = {CONFIRMED: 1, DELIVERY_DESK: 2, DELIVERED: 3}

# Order-level `status` values (list_orders / get_order).
ORDER_CONFIRMED = {"confirmed"}
ORDER_CANCELLED = {"canceled", "cancelled"}
ORDER_RETURNED = {"returned"}
ORDER_DELIVERED = {"delivered"}
ORDER_DISPATCHED = {"dispatched"}
# Seen in the account, intentionally no SMS: waiting for confirmation,
# postponed, incomplete checkout, and the merchant's custom "test" status.
ORDER_NO_SMS = {"pending", "scheduled", "abandoned", "test"}

# Carrier `deliveryStatus` codes for dispatched parcels (ZR Express).
# commande_recue = parcel registered with ZR but not yet handed over, so the
# customer-facing state is still "confirmed". Tassyir confirms and dispatches
# within seconds, so this is usually the first state an hourly run sees.
CARRIER_AWAITING_PICKUP = {"commande_recue"}
# Parcel physically with the delivery company (at desk, moving, out for delivery).
CARRIER_WITH_DELIVERY_COMPANY = {
    "confirme_au_bureau",
    "dispatch",
    "vers_wilaya",
    "sortie_en_livraison",
}
CARRIER_DELIVERED = {"livre", "encaisse"}

# Tassyir's carrier-independent `trackingStatus`, used when the carrier code
# is unknown. "to desk" is ambiguous (ZR uses it for both commande_recue and
# confirme_au_bureau), so it only counts when the carrier code settles it.
TRACKING_WITH_DELIVERY_COMPANY = {"in transit", "out for delivery"}
TRACKING_DELIVERED = {"delivered"}
TRACKING_RETURNED = {"returned"}


def map_status(order):
    """Return (automation_status or None, known: bool).

    `known` is False when the combination has never been seen, so the run
    summary can flag it for a mapping update instead of silently ignoring it.
    """
    status = (order.status or "").strip().lower()
    tracking = (order.tracking_status or "").strip().lower()
    carrier = (order.delivery_status or "").strip().lower()

    if order.source == "returns" or status in ORDER_RETURNED or tracking in TRACKING_RETURNED:
        return RETURNED, True
    if status in ORDER_CANCELLED:
        return CANCELLED, True
    if status in ORDER_DELIVERED or tracking in TRACKING_DELIVERED or carrier in CARRIER_DELIVERED:
        return DELIVERED, True
    if status in ORDER_DISPATCHED:
        if carrier in CARRIER_AWAITING_PICKUP:
            return CONFIRMED, True
        if carrier in CARRIER_WITH_DELIVERY_COMPANY or tracking in TRACKING_WITH_DELIVERY_COMPANY:
            return DELIVERY_DESK, True
        return None, False
    if status in ORDER_CONFIRMED:
        return CONFIRMED, True
    if status in ORDER_NO_SMS:
        return None, True
    return None, False


def raw_label(order):
    """Compact human-readable raw status, e.g. 'dispatched/to desk/confirme_au_bureau'."""
    parts = [order.status or "?"]
    if order.tracking_status or order.delivery_status:
        parts.append(order.tracking_status or "-")
        parts.append(order.delivery_status or "-")
    return "/".join(parts)
