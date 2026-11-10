from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (
    BinStatus,
    BottleRate,
    BottleScan,
    KioskUser,
    MetalStatus,
    TinCanRate,
    Transaction,
)


def normalize_bottle_label(label):
    """
    Convert model labels to a consistent format.

    Examples:
    Plastic_Bottle -> plastic bottle
    Tin Can        -> tin can
    No_Item        -> no item
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
    Save one stable camera result to the oldest active portal scan.

    Plastic Bottle:
        Accepted and earns bottle points.

    Tin Can:
        Accepted and earns tin-can points only when the metal detector
        reported metal within the last 10 seconds.

    Other Object:
        Rejected and earns zero points.

    No Item:
        Does not complete a scan.
    """
    label_key = normalize_bottle_label(label)

    def _bin_is_full(device_id):
        bin_status = (
            BinStatus.objects
            .select_for_update()
            .filter(device_id=device_id)
            .first()
        )

        return (
            bin_status is not None
            and (
                bin_status.is_full
                or bin_status.fill_percent == BinStatus.FULL
            )
        )

    if label_key not in {
        "plastic bottle",
        "tin can",
        "other object",
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
        BottleScan.objects.filter(
            status=BottleScan.WAITING,
            expires_at__lte=now,
        ).update(
            status=BottleScan.EXPIRED,
            completed_at=now,
        )

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

        plastic_bin_is_full = _bin_is_full(
            "plastic-bin"
        )

        tin_can_bin_is_full = _bin_is_full(
            "tin-can-bin"
        )

        if label_key == "plastic bottle":
            item_type = Transaction.PLASTIC_BOTTLE

            if plastic_bin_is_full:
                points_awarded = 0
                pieces = 0
                condition = Transaction.DIRTY
                scan.status = BottleScan.REJECTED
                rejection_reason = (
                    BottleScan.PLASTIC_BIN_FULL
                )
            else:
                rate = (
                    BottleRate.objects
                    .order_by("id")
                    .first()
                )

                if rate is None:
                    raise RuntimeError(
                        "Bottle rate is not configured."
                    )

                points_awarded = rate.points_per_bottle
                pieces = 1
                condition = Transaction.CLEAN
                scan.status = BottleScan.ACCEPTED
                rejection_reason = (
                    BottleScan.NO_REJECTION
                )

                user.points_balance += points_awarded
                user.total_pieces += 1

                user.save(
                    update_fields=[
                        "points_balance",
                        "total_pieces",
                    ]
                )

        elif label_key == "tin can":
            item_type = Transaction.TIN_CAN

            metal_recently_detected = (
                MetalStatus.objects.filter(
                    device_id="main-metal-sensor",
                    last_detected_at__gte=(
                        now - timedelta(seconds=10)
                    ),
                ).exists()
            )

            if not metal_recently_detected:
                points_awarded = 0
                pieces = 0
                condition = Transaction.DIRTY
                scan.status = BottleScan.REJECTED
                rejection_reason = BottleScan.NO_METAL

            elif tin_can_bin_is_full:
                points_awarded = 0
                pieces = 0
                condition = Transaction.DIRTY
                scan.status = BottleScan.REJECTED
                rejection_reason = (
                    BottleScan.TIN_CAN_BIN_FULL
                )

            else:
                rate = (
                    TinCanRate.objects
                    .order_by("id")
                    .first()
                )

                if rate is None:
                    raise RuntimeError(
                        "Tin-can rate is not configured."
                    )

                points_awarded = rate.points_per_tin_can
                pieces = 1
                condition = Transaction.CLEAN
                scan.status = BottleScan.ACCEPTED
                rejection_reason = (
                    BottleScan.NO_REJECTION
                )

                user.points_balance += points_awarded
                user.total_pieces += 1

                user.save(
                    update_fields=[
                        "points_balance",
                        "total_pieces",
                    ]
                )

        else:
            # other object
            points_awarded = 0
            pieces = 0
            condition = Transaction.DIRTY
            item_type = Transaction.OTHER_OBJECT
            scan.status = BottleScan.REJECTED
            rejection_reason = BottleScan.OTHER_OBJECT

        Transaction.objects.create(
            user=user,
            type=Transaction.DEPOSIT,
            pieces=pieces,
            weight_kg=None,
            condition=condition,
            item_type=item_type,
            points_delta=points_awarded,
        )

        scan.label = str(label).strip()
        scan.confidence_percent = confidence
        scan.points_awarded = points_awarded
        scan.rejection_reason = rejection_reason
        scan.completed_at = now

        scan.save(
            update_fields=[
                "status",
                "label",
                "confidence_percent",
                "points_awarded",
                "rejection_reason",
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
            "rejection_reason": rejection_reason,
            "new_balance": user.points_balance,
            "is_invalid": (
                label_key == "other object"
            ),
        }