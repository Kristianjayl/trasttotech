import uuid
import hmac
import json
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.utils import timezone
from datetime import timedelta
from .ml_classifier import classify_bottle

from .models import (
    KioskUser,
    BottleRate,
    WifiRate,
    Transaction,
    Voucher,
    BinStatus,
    BottleScan,
)

COOKIE_NAME = "kiosk_uid"

BOTTLE_SCAN_TIMEOUT_SECONDS = 90


def get_or_create_user(request):
    uid = request.COOKIES.get(COOKIE_NAME)
    created_cookie = False
    if not uid:
        uid = uuid.uuid4().hex
        created_cookie = True
    user, _ = KioskUser.objects.get_or_create(device_id=uid)

    # The portal is reached directly over the laptop hotspot, so
    # REMOTE_ADDR is the client's real hotspot IP (for example,
    # 192.168.137.25). Do not trust X-Forwarded-For here.
    client_ip = request.META.get("REMOTE_ADDR")
    user.last_ip = client_ip or None
    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_ip", "last_seen_at"])

    return user, uid, created_cookie


def _set_uid_cookie(response, uid):
    response.set_cookie(COOKIE_NAME, uid, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response

#--------------------------------------------------------------- utils ---
def _seed_rates_if_empty():
    if not BottleRate.objects.exists():
        BottleRate.objects.create(points_per_bottle=3)
    if not WifiRate.objects.exists():
        WifiRate.objects.bulk_create([
            WifiRate(points=5, minutes=10, label="10 Minutes"),
            WifiRate(points=10, minutes=20, label="20 Minutes"),
            WifiRate(points=30, minutes=45, label="45 Minutes"),
            WifiRate(points=50, minutes=60, label="1 Hour"),
        ])


def _remaining_seconds(user):
    if user.paused or not user.session_expires_at:
        return user.remaining_seconds
    delta = (user.session_expires_at - timezone.now()).total_seconds()
    return max(0, int(delta))


def _user_state(user):
    remaining_seconds = _remaining_seconds(user)
    recently_seen = (
        user.last_seen_at is not None
        and user.last_seen_at
        >= timezone.now() - timedelta(seconds=30)
    )

    return {
        "mac": user.mac_display(),
        "ip": user.last_ip or "Unknown",
        "points": user.points_balance,
        "remaining_seconds": remaining_seconds,
        "paused": user.paused,
        "connected": recently_seen,
        "wifi_access_active": (
            recently_seen
            and remaining_seconds > 0
            and not user.paused
        ),
    }


# ---------------------------------------------------------------- pages ---

@ensure_csrf_cookie
def portal(request):
    _seed_rates_if_empty()
    user, uid, created_cookie = get_or_create_user(request)
    bottle_rate = BottleRate.objects.first()
    wifi_rates = list(WifiRate.objects.values("points", "minutes", "label"))
    piece_rates = [
        {
            "pieces": (
                w["points"] + bottle_rate.points_per_bottle - 1
            ) // bottle_rate.points_per_bottle,
            "points": w["points"],
            "label": w["label"],
        }
    for w in wifi_rates
    ]
    response = render(request, "kiosk/portal.html", {
        "state": _user_state(user),
        "piece_rates": piece_rates,
        "wifi_rates": wifi_rates,
        "points_per_bottle": bottle_rate.points_per_bottle,
    })
    if created_cookie:
        _set_uid_cookie(response, uid)
    return response


# ------------------------------------------------------------------ api ---

@require_GET
def api_status(request):
    user, uid, created_cookie = get_or_create_user(request)
    resp = JsonResponse(_user_state(user))
    if created_cookie:
        _set_uid_cookie(resp, uid)
    return resp


@require_POST
def api_insert_start(request):
    """
    Open a database-backed camera scan for this portal user.
    Only one user can use the physical scanner at a time.
    """
    user, uid, created_cookie = get_or_create_user(request)
    now = timezone.now()
    expires_at = now + timedelta(
        seconds=BOTTLE_SCAN_TIMEOUT_SECONDS
    )

    with transaction.atomic():
        BottleScan.objects.filter(
            status=BottleScan.WAITING,
            expires_at__lte=now,
        ).update(
            status=BottleScan.EXPIRED,
            completed_at=now,
        )

        active_other_scan = (
            BottleScan.objects
            .select_for_update()
            .filter(
                status=BottleScan.WAITING,
                expires_at__gt=now,
            )
            .exclude(user=user)
            .first()
        )

        if active_other_scan is not None:
            response = JsonResponse(
                {
                    "ok": False,
                    "error": "scanner_busy",
                    "message": (
                        "The bottle scanner is currently "
                        "being used by another user."
                    ),
                },
                status=409,
            )
            if created_cookie:
                _set_uid_cookie(response, uid)
            return response

        BottleScan.objects.filter(
            user=user,
            status=BottleScan.WAITING,
        ).update(
            status=BottleScan.CANCELLED,
            completed_at=now,
        )

        scan = BottleScan.objects.create(
            user=user,
            status=BottleScan.WAITING,
            expires_at=expires_at,
        )

    response = JsonResponse(
        {
            "ok": True,
            "scan_id": scan.id,
            "status": scan.status,
            "seconds_left": BOTTLE_SCAN_TIMEOUT_SECONDS,
        }
    )
    if created_cookie:
        _set_uid_cookie(response, uid)
    return response


@require_GET
def api_insert_poll(request):
    """
    Return the latest camera-scan state for this portal user.
    """
    user, uid, created_cookie = get_or_create_user(request)
    scan = (
        BottleScan.objects
        .filter(user=user)
        .order_by("-started_at")
        .first()
    )

    if scan is None:
        response = JsonResponse(
            {"ok": False, "error": "no_scan"},
            status=404,
        )
        if created_cookie:
            _set_uid_cookie(response, uid)
        return response

    now = timezone.now()
    if (
        scan.status == BottleScan.WAITING
        and scan.expires_at <= now
    ):
        scan.status = BottleScan.EXPIRED
        scan.completed_at = now
        scan.save(
            update_fields=["status", "completed_at"]
        )

    seconds_left = 0
    if scan.status == BottleScan.WAITING:
        seconds_left = max(
            0,
            int((scan.expires_at - now).total_seconds()),
        )

    user.refresh_from_db(
        fields=["points_balance", "total_pieces"]
    )

    response = JsonResponse(
        {
            "ok": True,
            "scan_id": scan.id,
            "status": scan.status,
            "done": scan.status != BottleScan.WAITING,
            "seconds_left": seconds_left,
            "label": scan.label or None,
            "confidence_percent": (
                float(scan.confidence_percent)
                if scan.confidence_percent is not None
                else None
            ),
            "points_awarded": scan.points_awarded,
            "new_balance": user.points_balance,
            "is_invalid": (
                scan.label.strip().lower() == "invalid"
                if scan.label
                else False
            ),
        }
    )
    if created_cookie:
        _set_uid_cookie(response, uid)
    return response


@require_POST
def api_insert_confirm(request):
    """
    Compatibility endpoint for the current portal JavaScript.
    It reads the saved camera result and never awards points twice.
    """
    user, uid, created_cookie = get_or_create_user(request)
    scan = (
        BottleScan.objects
        .filter(user=user)
        .order_by("-started_at")
        .first()
    )

    if scan is None:
        response = JsonResponse(
            {"ok": False, "error": "no_scan"},
            status=404,
        )
        if created_cookie:
            _set_uid_cookie(response, uid)
        return response

    if scan.status == BottleScan.WAITING:
        return JsonResponse(
            {"ok": False, "error": "scan_not_finished"},
            status=409,
        )

    user.refresh_from_db(
        fields=["points_balance", "total_pieces"]
    )
    is_invalid = (
        scan.label.strip().lower() == "invalid"
        if scan.label
        else False
    )

    if scan.status == BottleScan.ACCEPTED:
        condition = Transaction.CLEAN
        pieces = 1
    elif scan.status == BottleScan.REJECTED:
        condition = Transaction.DIRTY
        pieces = 0 if is_invalid else 1
    else:
        condition = None
        pieces = 0

    response = JsonResponse(
        {
            "ok": True,
            "pieces": pieces,
            "points_awarded": scan.points_awarded,
            "new_balance": user.points_balance,
            "condition": condition,
            "status": scan.status,
            "label": scan.label or None,
            "confidence_percent": (
                float(scan.confidence_percent)
                if scan.confidence_percent is not None
                else None
            ),
            "is_invalid": is_invalid,
        }
    )
    if created_cookie:
        _set_uid_cookie(response, uid)
    return response


@require_POST
def api_insert_cancel(request):
    user, uid, created_cookie = get_or_create_user(request)
    now = timezone.now()
    updated = BottleScan.objects.filter(
        user=user,
        status=BottleScan.WAITING,
    ).update(
        status=BottleScan.CANCELLED,
        completed_at=now,
    )

    response = JsonResponse(
        {"ok": True, "cancelled": updated > 0}
    )
    if created_cookie:
        _set_uid_cookie(response, uid)
    return response


@require_POST
def api_redeem_wifi(request):
    import json
    body = json.loads(request.body or "{}")
    points_cost = int(body.get("points", 0))
    user, uid, _ = get_or_create_user(request)

    tier = WifiRate.objects.filter(points=points_cost).first()
    if not tier:
        return JsonResponse({"error": "invalid tier"}, status=400)
    if user.points_balance < tier.points:
        return JsonResponse({"error": "insufficient_points"}, status=400)

    user.points_balance -= tier.points
    current_remaining = _remaining_seconds(user)
    user.remaining_seconds = current_remaining + tier.minutes * 60
    user.session_expires_at = timezone.now() + timedelta(seconds=user.remaining_seconds)
    user.paused = False
    user.save()
    Transaction.objects.create(user=user, type=Transaction.WIFI_REDEEM,
                                points_delta=-tier.points, wifi_minutes=tier.minutes)
    return JsonResponse({"ok": True, **_user_state(user)})


@require_POST
def api_pause_toggle(request):
    user, uid, _ = get_or_create_user(request)
    if user.paused:
        user.session_expires_at = timezone.now() + timedelta(seconds=user.remaining_seconds)
        user.paused = False
    else:
        user.remaining_seconds = _remaining_seconds(user)
        user.paused = True
        user.paused_at = timezone.now()
    user.save()
    return JsonResponse(_user_state(user))


@require_POST
def api_voucher_generate(request):
    import json
    body = json.loads(request.body or "{}")
    points_cost = int(body.get("points", 0))
    user, uid, _ = get_or_create_user(request)

    MIN_POINTS_FOR_VOUCHER = 50  # mirrors the 5-bottle minimum, shown on the kiosk
    if points_cost < MIN_POINTS_FOR_VOUCHER:
        return JsonResponse({"error": "below_minimum"}, status=400)
    if user.points_balance < points_cost:
        return JsonResponse({"error": "insufficient_points"}, status=400)

    user.points_balance -= points_cost
    user.save()
    code = "VC-" + uuid.uuid4().hex[:6].upper()
    Voucher.objects.create(code=code, user=user, points_used=points_cost)
    Transaction.objects.create(user=user, type=Transaction.VOUCHER, points_delta=-points_cost)
    return JsonResponse({"ok": True, "code": code, "new_balance": user.points_balance})


@require_POST
def api_voucher_submit(request):
    import json
    body = json.loads(request.body or "{}")
    code = (body.get("code") or "").strip().upper()
    try:
        voucher = Voucher.objects.get(code=code)
    except Voucher.DoesNotExist:
        return JsonResponse({"ok": False, "reason": "invalid"})

    if voucher.status != Voucher.PENDING:
        return JsonResponse({"ok": False, "reason": "invalid"})

    voucher.status = Voucher.REDEEMED
    voucher.redeemed_at = timezone.now()
    voucher.save()
    return JsonResponse({"ok": True})

@require_POST
def api_classify_bottle(request):
    uploaded_image = request.FILES.get("image")

    if uploaded_image is None:
        return JsonResponse(
            {
                "ok": False,
                "error": "image_required",
            },
            status=400,
        )

    if uploaded_image.size > 5 * 1024 * 1024:
        return JsonResponse(
            {
                "ok": False,
                "error": "image_too_large",
            },
            status=413,
        )

    if not uploaded_image.content_type.startswith("image/"):
        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_image_type",
            },
            status=400,
        )

    try:
        result = classify_bottle(uploaded_image)
    except FileNotFoundError as error:
        return JsonResponse(
            {
                "ok": False,
                "error": "model_unavailable",
                "details": str(error),
            },
            status=503,
        )
    except (OSError, ValueError):
        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_image",
            },
            status=400,
        )

    return JsonResponse(
        {
            "ok": True,
            **result,
        }
    )

@require_GET
def api_device_ping(request):
    return JsonResponse({
        "ok": True,
        "message": "ESP32 reached Django",
    })

@csrf_exempt
@require_POST
def api_bin_status(request):
    expected_token = settings.ESP32_API_TOKEN
    provided_token = request.headers.get(
        "X-Device-Token",
        "",
    )

    if (
        not expected_token
        or not hmac.compare_digest(
            provided_token,
            expected_token,
        )
    ):
        return JsonResponse(
            {
                "ok": False,
                "error": "unauthorized_device",
            },
            status=403,
        )

    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_json",
            },
            status=400,
        )

    is_full = body.get("is_full")

    if not isinstance(is_full, bool):
        return JsonResponse(
            {
                "ok": False,
                "error": "is_full_must_be_boolean",
            },
            status=400,
        )

    device_id = (
        str(body.get("device_id") or "main-bin")
        .strip()[:64]
        or "main-bin"
    )

    bin_status, _ = BinStatus.objects.update_or_create(
        device_id=device_id,
        defaults={
            "is_full": is_full,
        },
    )

    return JsonResponse({
        "ok": True,
        "device_id": bin_status.device_id,
        "is_full": bin_status.is_full,
        "status": (
            "full"
            if bin_status.is_full
            else "not_full"
        ),
        "updated_at": bin_status.updated_at.isoformat(),
    })
