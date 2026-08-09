import uuid
import hmac
import json
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse
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
)

COOKIE_NAME = "kiosk_uid"

# Simple in-memory tracker for "bottle currently being weighed" per user.
# On real hardware this state lives on the ESP32 (load-cell reading), not
# in the web server -- here it's simulated so the front-end has something
# to poll and react to.
_active_deposits = {}


def get_or_create_user(request):
    uid = request.COOKIES.get(COOKIE_NAME)
    created_cookie = False
    if not uid:
        uid = uuid.uuid4().hex
        created_cookie = True
    user, _ = KioskUser.objects.get_or_create(device_id=uid)
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
    return {
        "mac": user.mac_display(),
        "ip": "10.42.0.1",
        "points": user.points_balance,
        "remaining_seconds": _remaining_seconds(user),
        "paused": user.paused,
        "connected": True,
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
    Begin a deposit session. On real hardware this is the moment the IR
    sensor detects a bottle and the ESP32 confirms it via the break-beam.
    Here we simulate a short detection window instead of a real sensor.

    """
    user, uid, _ = get_or_create_user(request)
    _active_deposits[user.id] = {"started_at": timezone.now()}
    return JsonResponse({"ok": True})


@require_GET
def api_insert_poll(request):
    """
    Simulated bottle detection. Replace this with a real check against
    the IR sensor's break-beam count when hardware is connected.
    Per-piece means we don't care about weight anymore -- just "was a
    bottle detected, yes or no."
    """
    user, uid, _ = get_or_create_user(request)
    session = _active_deposits.get(user.id)
    if not session:
        return JsonResponse({"error": "no active deposit"}, status=400)

    elapsed = (timezone.now() - session["started_at"]).total_seconds()
    seconds_left = max(0, 4 - int(elapsed))  # short window, just confirming presence
    if seconds_left == 0 and session.get("confirmed_piece") is None:
        session["confirmed_piece"] = True

    return JsonResponse({
        "seconds_left": seconds_left,
        "done": seconds_left == 0,
    })


@require_POST
def api_insert_confirm(request):
    """
    Finalize the deposit. Currently simulates the clean/dirty camera
    check with a random result (mostly clean, some dirty) -- replace
    this with the real ESP32-CAM/Edge Impulse result once that's wired in.
    Dirty bottles are rejected (0 points) but still logged, so Reports
    has real data to chart.
    """
    import random
    user, uid, _ = get_or_create_user(request)
    session = _active_deposits.pop(user.id, None)
    piece_confirmed = bool((session or {}).get("confirmed_piece"))

    if not piece_confirmed:
        return JsonResponse({"pieces": 0, "points_awarded": 0, "new_balance": user.points_balance, "condition": None})

    # SIMULATED -- swap for real camera classifier result later
    is_clean = random.random() < 0.5  # ~50% clean, ~50% dirty, just for demo data
    condition = Transaction.CLEAN if is_clean else Transaction.DIRTY

    rate = BottleRate.objects.first()
    points = rate.points_per_bottle if (is_clean and rate) else 0

    if is_clean:
        user.points_balance += points
        user.total_pieces += 1
        user.save()

    simulated_weight = round(random.uniform(0.35, 0.55), 2)  # kg tracking, unrelated to points
    Transaction.objects.create(user=user, type=Transaction.DEPOSIT,
                                pieces=1, weight_kg=simulated_weight,
                                condition=condition, points_delta=points)

    return JsonResponse({
        "pieces": 1, "points_awarded": points, "new_balance": user.points_balance,
        "condition": condition,
    })


@require_POST
def api_insert_cancel(request):
    user, uid, _ = get_or_create_user(request)
    _active_deposits.pop(user.id, None)
    return JsonResponse({"ok": True})


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