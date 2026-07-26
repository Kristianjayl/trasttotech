import uuid
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from datetime import timedelta

from .models import KioskUser, PlasticRate, WifiRate, Transaction, Voucher

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


def _seed_rates_if_empty():
    if not PlasticRate.objects.exists():
        PlasticRate.objects.bulk_create([
            PlasticRate(weight_kg=0.10, points=10),
            PlasticRate(weight_kg=0.25, points=25),
            PlasticRate(weight_kg=0.50, points=50),
            PlasticRate(weight_kg=1.00, points=100),
            PlasticRate(weight_kg=2.00, points=200),
        ])
    if not WifiRate.objects.exists():
        WifiRate.objects.bulk_create([
            WifiRate(points=10, minutes=15, label="15 Minutes"),
            WifiRate(points=25, minutes=30, label="30 Minutes"),
            WifiRate(points=50, minutes=60, label="1 Hour"),
            WifiRate(points=100, minutes=120, label="2 Hours"),
            WifiRate(points=200, minutes=360, label="6 Hours (Maximum Daily)"),
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
    plastic_rates = list(PlasticRate.objects.values("weight_kg", "points"))
    wifi_rates = list(WifiRate.objects.values("points", "minutes", "label"))
    response = render(request, "kiosk/portal.html", {
        "state": _user_state(user),
        "plastic_rates": plastic_rates,
        "wifi_rates": wifi_rates,
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
    sensor detects a bottle and the ESP32 starts reading the load cell.
    Here we simulate a bottle's weight climbing over ~30 seconds.
    """
    user, uid, _ = get_or_create_user(request)
    _active_deposits[user.id] = {"started_at": timezone.now(), "final_kg": None}
    return JsonResponse({"ok": True})


@require_GET
def api_insert_poll(request):
    """
    Simulated load-cell reading. Replace this function's body with a real
    HTTP call to the machine's current weight endpoint when hardware is
    connected -- the response shape should stay the same so the front-end
    doesn't need to change.
    """
    user, uid, _ = get_or_create_user(request)
    session = _active_deposits.get(user.id)
    if not session:
        return JsonResponse({"error": "no active deposit"}, status=400)

    elapsed = (timezone.now() - session["started_at"]).total_seconds()
    seconds_left = max(0, 30 - int(elapsed))
    weight_kg = round(min(0.25, (elapsed / 12) * 0.25), 2)
    if seconds_left == 0 and session["final_kg"] is None:
        session["final_kg"] = weight_kg

    return JsonResponse({
        "weight_kg": weight_kg,
        "seconds_left": seconds_left,
        "done": seconds_left == 0,
    })


@require_POST
def api_insert_confirm(request):
    """
    Finalize the deposit: look up points for the weight against
    PlasticRate, credit the user, and log a Transaction. This is the
    exact place a real deposit event from the ESP32 would land.
    """
    user, uid, _ = get_or_create_user(request)
    session = _active_deposits.pop(user.id, None)
    weight_kg = (session or {}).get("final_kg") or 0

    rate = PlasticRate.objects.filter(weight_kg__lte=weight_kg).order_by("-weight_kg").first()
    points = rate.points if rate else 0

    if points > 0:
        user.points_balance += points
        user.total_kg += weight_kg
        user.save()
        Transaction.objects.create(user=user, type=Transaction.DEPOSIT,
                                    weight_kg=weight_kg, points_delta=points)

    return JsonResponse({"weight_kg": weight_kg, "points_awarded": points,
                          "new_balance": user.points_balance})


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

    MIN_KG_EQUIVALENT_POINTS = 50  # mirrors the 0.50kg minimum shown on the kiosk
    if points_cost < MIN_KG_EQUIVALENT_POINTS:
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