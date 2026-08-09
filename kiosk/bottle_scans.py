from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (
    BottleRate,
    BottleScan,
    KioskUser,
    Transaction,
)


def normalize_bottle_label(label):
    """
    Convert model labels to a consistent format.

    Examples:
    Clean      -> clean
    No Bottle  -> no bottle
    no_bottle  -> no bottle
    """
    return (
        str(label)
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )


def complete_waiting_scan(
    label,
    confidence_percent,
):
    """
    Save one stable camera result to the oldest
    active portal scan.

    Clean:
        Accepted and receives points.

    Reject:
        Rejected bottle and receives zero points.

    Invalid:
        Rejected invalid object and receives zero points.

    No Bottle:
        Does not complete the scan.
    """
    label_key = normalize_bottle_label(label)

    if label_key not in {
        "clean",
        "reject",
        "invalid",
    }:
        return None

    now = timezone.now()

    confidence = Decimal(
        str(confidence_percent)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    with transaction.atomic():
        # Close waiting scans whose time has ended.
        BottleScan.objects.filter(
            status=BottleScan.WAITING,
            expires_at__lte=now,
        ).update(
            status=BottleScan.EXPIRED,
            completed_at=now,
        )

        # Find the oldest scan that is still waiting.
        scan = (
            BottleScan.objects
            .select_for_update()
            .filter(
                status=BottleScan.WAITING,
                expires_at__gt=now,
            )
            .order_by("started_at")
            .first()
        )

        if scan is None:
            return None

        user = (
            KioskUser.objects
            .select_for_update()
            .get(pk=scan.user_id)
        )

        if label_key == "clean":
            rate = (
                BottleRate.objects
                .order_by("id")
                .first()
            )

            if rate is None:
                raise RuntimeError(
                    "Bottle rate is not configured."
                )

            points_awarded = (
                rate.points_per_bottle
            )

            pieces = 1
            condition = Transaction.CLEAN
            scan.status = BottleScan.ACCEPTED

            user.points_balance += points_awarded
            user.total_pieces += 1

            user.save(
                update_fields=[
                    "points_balance",
                    "total_pieces",
                ]
            )

        elif label_key == "reject":
            # It is a bottle, but it is not acceptable.
            points_awarded = 0
            pieces = 1
            condition = Transaction.DIRTY
            scan.status = BottleScan.REJECTED

        else:
            # Invalid means it is not a valid bottle.
            points_awarded = 0
            pieces = 0
            condition = Transaction.DIRTY
            scan.status = BottleScan.REJECTED

        Transaction.objects.create(
            user=user,
            type=Transaction.DEPOSIT,
            pieces=pieces,
            weight_kg=None,
            condition=condition,
            points_delta=points_awarded,
        )

        scan.label = str(label).strip()
        scan.confidence_percent = confidence
        scan.points_awarded = points_awarded
        scan.completed_at = now

        scan.save(
            update_fields=[
                "status",
                "label",
                "confidence_percent",
                "points_awarded",
                "completed_at",
            ]
        )

        return {
            "scan_id": scan.id,
            "status": scan.status,
            "label": scan.label,
            "confidence_percent": float(
                scan.confidence_percent
            ),
            "points_awarded": points_awarded,
            "new_balance": user.points_balance,
            "is_invalid": (
                label_key == "invalid"
            ),
        }