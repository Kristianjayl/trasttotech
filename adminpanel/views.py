from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import TruncMonth, TruncYear
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .decorators import role_required
from .models import StaffProfile
from kiosk.models import (
    KioskUser,
    Transaction,
    Voucher,
    BottleRate,
    WifiRate,
    BinStatus,
    BottleScan,
    TinCanRate,
)

# ============================================================
# AUTH
# ============================================================

class StaffLoginView(LoginView):
    template_name = "adminpanel/login.html"


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def overview(request):
    today = timezone.now().date()

    total_pieces = Transaction.objects.filter(type=Transaction.DEPOSIT).aggregate(
        total=Sum("pieces"))["total"] or 0
    total_plastic_bottles = (
        Transaction.objects
        .filter(
            type=Transaction.DEPOSIT,
            item_type=Transaction.PLASTIC_BOTTLE,
        )
        .aggregate(total=Sum("pieces"))["total"]
        or 0
    )

    total_tin_cans = (
        Transaction.objects
        .filter(
            type=Transaction.DEPOSIT,
            item_type=Transaction.TIN_CAN,
        )
        .aggregate(total=Sum("pieces"))["total"]
        or 0
    )
    total_kg = Transaction.objects.filter(type=Transaction.DEPOSIT).aggregate(
        total=Sum("weight_kg"))["total"] or 0
    # Older demo transactions may have been created with different point
    # values. The overview should reflect the currently collected items
    # using the administrator's current rates.
    bottle_rate = BottleRate.objects.order_by("id").first()
    tin_can_rate = TinCanRate.objects.order_by("id").first()
    bottle_points = bottle_rate.points_per_bottle if bottle_rate else 5
    tin_can_points = tin_can_rate.points_per_tin_can if tin_can_rate else 5
    points_issued = (
        total_plastic_bottles * bottle_points
        + total_tin_cans * tin_can_points
    )
    wifi_sessions = Transaction.objects.filter(type=Transaction.WIFI_REDEEM).count()
    # A portal client reports its presence every eight seconds. Treat clients
    # seen during the last 30 seconds as connected to the prototype hotspot.
    active_users = KioskUser.objects.filter(
        last_seen_at__gte=timezone.now() - timedelta(seconds=30)
    ).count()
    internet_minutes = Transaction.objects.filter(type=Transaction.WIFI_REDEEM).aggregate(
        total=Sum("wifi_minutes"))["total"] or 0

    recent_transactions = Transaction.objects.select_related("user").order_by("-created_at")[:10]

    plastic_bin_status = BinStatus.objects.filter(
    device_id="plastic-bin"
    ).first()

    tin_can_bin_status = BinStatus.objects.filter(
        device_id="tin-can-bin"
    ).first()

    return render(request, "adminpanel/overview.html", {
    "total_pieces": total_pieces,
    "total_plastic_bottles": total_plastic_bottles,
    "total_tin_cans": total_tin_cans,
    "total_kg": round(total_kg, 2),
    "points_issued": points_issued,
    "wifi_sessions": wifi_sessions,
    "active_users": active_users,
    "internet_hours": round(internet_minutes / 60, 1),
    "recent_transactions": recent_transactions,
    "plastic_bin_status": plastic_bin_status,
    "tin_can_bin_status": tin_can_bin_status,
    "today": today,
    })

# ============================================================
# CLIENT USERS (kiosk customers -- points, bottle counts, etc.)
# Different from Staff Accounts below, which are Admin/SK dashboard logins.
# ============================================================

@login_required
def users_list(request):
    users = KioskUser.objects.order_by("-points_balance")
    return render(request, "adminpanel/users.html", {"users": users})


@role_required('admin')
def user_create(request):
    if request.method == "POST":
        KioskUser.objects.create(
            device_id=request.POST.get("device_id"),
            points_balance=int(request.POST.get("points_balance") or 0),
            total_pieces=int(request.POST.get("total_pieces") or 0),
        )
        return redirect("staff_users")
    return render(request, "adminpanel/user_form.html", {"mode": "create"})


@role_required('admin')
def user_edit(request, user_id):
    kiosk_user = get_object_or_404(KioskUser, id=user_id)
    if request.method == "POST":
        kiosk_user.points_balance = int(request.POST.get("points_balance") or 0)
        kiosk_user.total_pieces = int(request.POST.get("total_pieces") or 0)
        kiosk_user.save()
        return redirect("staff_users")
    return render(request, "adminpanel/user_form.html", {"mode": "edit", "kiosk_user": kiosk_user})


@role_required('admin')
def user_delete(request, user_id):
    kiosk_user = get_object_or_404(KioskUser, id=user_id)
    if request.method == "POST":
        kiosk_user.delete()
        return redirect("staff_users")
    return render(request, "adminpanel/user_confirm_delete.html", {"kiosk_user": kiosk_user})


# ============================================================
# TRANSACTIONS & REWARDS
# ============================================================

@login_required
def transactions_list(request):
    type_filter = request.GET.get("type", "all")
    qs = Transaction.objects.select_related("user").order_by("-created_at")
    if type_filter != "all":
        qs = qs.filter(type=type_filter)
    return render(request, "adminpanel/transactions.html", {
        "transactions": qs[:200],
        "type_filter": type_filter,
        "type_choices": Transaction.TYPE_CHOICES,
    })


@login_required
def rewards(request):
    vouchers = Voucher.objects.select_related("user").order_by("-generated_at")[:100]
    stats = {
        "generated": Voucher.objects.count(),
        "redeemed": Voucher.objects.filter(status=Voucher.REDEEMED).count(),
        "pending": Voucher.objects.filter(status=Voucher.PENDING).count(),
    }
    return render(request, "adminpanel/rewards.html", {"vouchers": vouchers, "stats": stats})


# ============================================================
# ADMIN-ONLY: RATES & SETTINGS
# Restricted via @role_required('admin') -- SK cannot access these.
# ============================================================

@role_required('admin')
def rates(request):
    bottle_rate = BottleRate.objects.order_by("id").first()
    if bottle_rate is None:
        bottle_rate = BottleRate.objects.create(
            points_per_bottle=5,
        )

    tin_can_rate = TinCanRate.objects.order_by("id").first()
    if tin_can_rate is None:
        tin_can_rate = TinCanRate.objects.create(
            points_per_tin_can=5,
        )

    if request.method == "POST":
        bottle_rate.points_per_bottle = int(
            request.POST.get("points_per_bottle")
        )
        bottle_rate.save()

        tin_can_rate.points_per_tin_can = int(
            request.POST.get("points_per_tin_can")
        )
        tin_can_rate.save()

        for wr in WifiRate.objects.all():
            new_val = request.POST.get(
                f"wifi_points_{wr.id}"
            )
            if new_val:
                wr.points = int(new_val)
                wr.save()

        return redirect("staff_rates")

    return render(
        request,
        "adminpanel/rates.html",
        {
            "bottle_rate": bottle_rate,
            "tin_can_rate": tin_can_rate,
            "wifi_rates": WifiRate.objects.order_by("points"),
        },
    )


@role_required('admin')
def settings_page(request):
    return render(request, "adminpanel/settings.html")


# ============================================================
# ADMIN-ONLY: STAFF ACCOUNTS (Admin/SK dashboard logins)
# Different from Client Users above. Also restricted to Admin only.
# ============================================================

@role_required('admin')
def staff_accounts_list(request):
    profiles = StaffProfile.objects.select_related("user").order_by("user__username")
    return render(request, "adminpanel/staff_accounts.html", {"profiles": profiles})


@role_required('admin')
def staff_account_create(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        role = request.POST.get("role")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        if User.objects.filter(username=username).exists():
            return render(request, "adminpanel/staff_account_form.html", {
                "mode": "create", "error": "That username already exists.",
                "submitted": request.POST,
            })
        if email and User.objects.filter(email__iexact=email).exists():
            return render(request, "adminpanel/staff_account_form.html", {
                "mode": "create", "error": "That email address is already in use.",
                "submitted": request.POST,
            })
        new_user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        StaffProfile.objects.create(user=new_user, role=role)
        return redirect("staff_accounts_list")
    return render(request, "adminpanel/staff_account_form.html", {"mode": "create"})


@role_required('admin')
def staff_account_edit(request, profile_id):
    profile = get_object_or_404(StaffProfile, id=profile_id)
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        if email and User.objects.exclude(id=profile.user_id).filter(
            email__iexact=email
        ).exists():
            return render(request, "adminpanel/staff_account_form.html", {
                "mode": "edit",
                "profile": profile,
                "error": "That email address is already in use.",
            })
        profile.role = request.POST.get("role")
        profile.save()
        profile.user.first_name = first_name
        profile.user.last_name = last_name
        profile.user.email = email
        new_password = request.POST.get("password")
        if new_password:
            profile.user.set_password(new_password)
        profile.user.save()
        return redirect("staff_accounts_list")
    return render(request, "adminpanel/staff_account_form.html", {"mode": "edit", "profile": profile})


@role_required('admin')
def staff_account_delete(request, profile_id):
    profile = get_object_or_404(StaffProfile, id=profile_id)
    if request.method == "POST":
        if profile.user == request.user:
            return render(request, "adminpanel/staff_account_confirm_delete.html", {
                "profile": profile, "error": "You can't delete your own account while logged in as it."
            })
        profile.user.delete()  # deletes the User; StaffProfile cascades with it
        return redirect("staff_accounts_list")
    return render(request, "adminpanel/staff_account_confirm_delete.html", {"profile": profile})


# ============================================================
# LOGS
# ============================================================

@login_required
def logs(request):
    # Reusing Transaction as the log source for now -- once hardware is
    # wired in, real error/maintenance events would also feed this,
    # ideally via a dedicated Log model. Fine as a placeholder for now.
    entries = Transaction.objects.select_related("user").order_by("-created_at")[:100]
    return render(request, "adminpanel/logs.html", {"entries": entries})


# ============================================================
# FOOTER PAGES
# ============================================================

@login_required
def about(request):
    return render(request, "adminpanel/about.html")


@login_required
def privacy_policy(request):
    return render(request, "adminpanel/privacy_policy.html")

@login_required
def reports(request):
    deposits = Transaction.objects.filter(
        type=Transaction.DEPOSIT,
        item_type__in=[
            Transaction.PLASTIC_BOTTLE,
            Transaction.TIN_CAN,
        ],
    )

    monthly_raw = (
        deposits.annotate(period=TruncMonth("created_at"))
        .values("period", "item_type")
        .annotate(count=Sum("pieces"))
        .order_by("period")
    )

    yearly_raw = (
        deposits.annotate(period=TruncYear("created_at"))
        .values("period", "item_type")
        .annotate(count=Sum("pieces"))
        .order_by("period")
    )

    def pivot(raw, fmt):
        buckets = {}

        for row in raw:
            key = row["period"].strftime(fmt)
            buckets.setdefault(
                key,
                {
                    "plastic": 0,
                    "tin": 0,
                },
            )

            item_key = {
                Transaction.PLASTIC_BOTTLE: "plastic",
                Transaction.TIN_CAN: "tin",
            }.get(row["item_type"])

            if item_key:
                buckets[key][item_key] = row["count"] or 0

        return buckets

    def with_bar_widths(buckets):
        rows = []
        max_total = max(
            [
                values["plastic"] + values["tin"]
                for values in buckets.values()
            ],
            default=1,
        ) or 1

        for label, values in buckets.items():
            total = values["plastic"] + values["tin"]

            rows.append(
                {
                    "label": label,
                    "plastic": values["plastic"],
                    "tin": values["tin"],
                    "total": total,
                    "plastic_pct": round(
                        (values["plastic"] / max_total) * 100,
                        1,
                    ),
                    "tin_pct": round(
                        (values["tin"] / max_total) * 100,
                        1,
                    ),
                }
            )

        return rows

    monthly = with_bar_widths(
        pivot(monthly_raw, "%b %Y")
    )
    yearly = with_bar_widths(
        pivot(yearly_raw, "%Y")
    )

    return render(
        request,
        "adminpanel/reports.html",
        {
            "monthly": monthly,
            "yearly": yearly,
        },
    )

@login_required
@require_GET
def bin_status_live(request):
    def make_status(device_id):
        bin_status = BinStatus.objects.filter(
            device_id=device_id
        ).first()

        if bin_status is None:
            return {
                "available": False,
            }

        return {
            "available": True,
            "fill_percent": bin_status.fill_percent,
            "is_full": bin_status.is_full,
            "status": (
                "full"
                if bin_status.is_full
                else "empty"
            ),
            "updated_at": bin_status.updated_at.isoformat(),
        }

    return JsonResponse({
        "ok": True,
        "plastic_bin": make_status("plastic-bin"),
        "tin_can_bin": make_status("tin-can-bin"),
    })


@login_required
@require_GET
def bottle_scan_live(request):
    """Return the newest item-scanner state for the live dashboard."""
    scan = (
        BottleScan.objects
        .select_related("user")
        .order_by("-started_at")
        .first()
    )

    if scan is None:
        return JsonResponse({
            "ok": True,
            "available": False,
            "display_status": "unknown",
            "message": "No bottle scan recorded yet",
        })

    now = timezone.now()
    status = scan.status

    # A browser may close before polling an expired waiting scan. Report the
    # correct live state without requiring the portal to make another request.
    if status == BottleScan.WAITING and scan.expires_at <= now:
        status = BottleScan.EXPIRED

    label = scan.label.strip() or None
    label_key = (
        (label or "")
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )

    if status == BottleScan.WAITING:
        display_status = "scanning"
        message = "Waiting for the camera to classify an item"
    elif status == BottleScan.ACCEPTED:
        display_status = "accepted"

        if label_key == "plastic bottle":
            message = "Plastic bottle accepted"
        elif label_key == "tin can":
            message = "Tin can accepted"
        else:
            message = "Item accepted"
    elif (
        status == BottleScan.REJECTED
        and scan.rejection_reason
        == BottleScan.PLASTIC_BIN_FULL
    ):
        display_status = "bin_full"
        message = "Plastic bottle bin is full"

    elif (
        status == BottleScan.REJECTED
        and scan.rejection_reason
        == BottleScan.TIN_CAN_BIN_FULL
    ):
        display_status = "bin_full"
        message = "Tin can bin is full"

    elif (
        status == BottleScan.REJECTED
        and scan.rejection_reason
        == BottleScan.NO_METAL
    ):
        display_status = "rejected"
        message = "Tin can was not metal-verified"

    elif (
        status == BottleScan.REJECTED
        and label_key == "other object"
    ):
        display_status = "invalid"
        message = "Invalid object detected"

    elif status == BottleScan.REJECTED:
        display_status = "rejected"
        message = "Item rejected"
    elif status == BottleScan.CANCELLED:
        display_status = "cancelled"
        message = "Item scan cancelled"
    elif status == BottleScan.EXPIRED:
        display_status = "expired"
        message = "Item scan timed out"
    else:
        display_status = "unknown"
        message = "Unknown item-scanner state"

    confidence = (
        float(scan.confidence_percent)
        if scan.confidence_percent is not None
        else None
    )
    event_time = scan.completed_at or scan.started_at
    seconds_left = 0

    if status == BottleScan.WAITING:
        seconds_left = max(
            0,
            int((scan.expires_at - now).total_seconds()),
        )

    return JsonResponse({
        "ok": True,
        "available": True,
        "scan_id": scan.id,
        "status": status,
        "display_status": display_status,
        "message": message,
        "label": label,
        "rejection_reason": (
            scan.rejection_reason or None
        ),
        "confidence_percent": confidence,
        "points_awarded": scan.points_awarded,
        "user": scan.user.mac_display(),
        "seconds_left": seconds_left,
        "started_at": scan.started_at.isoformat(),
        "updated_at": event_time.isoformat(),
    })


@login_required
@require_GET
def wifi_users_live(request):
    """Return portal clients recently seen on the prototype hotspot."""
    now = timezone.now()
    cutoff = now - timedelta(seconds=30)
    users = list(
        KioskUser.objects
        .filter(last_seen_at__gte=cutoff)
        .order_by("-last_seen_at")
    )

    client_rows = []
    active_access_count = 0

    for kiosk_user in users:
        if kiosk_user.paused or not kiosk_user.session_expires_at:
            remaining_seconds = max(0, kiosk_user.remaining_seconds)
        else:
            remaining_seconds = max(
                0,
                int(
                    (
                        kiosk_user.session_expires_at - now
                    ).total_seconds()
                ),
            )

        access_active = (
            remaining_seconds > 0
            and not kiosk_user.paused
        )

        if access_active:
            access_status = "active"
            active_access_count += 1
        elif kiosk_user.paused and remaining_seconds > 0:
            access_status = "paused"
        else:
            access_status = "no_time"

        client_rows.append({
            "user": kiosk_user.mac_display(),
            "ip": kiosk_user.last_ip or "Unknown",
            "access_status": access_status,
            "remaining_seconds": remaining_seconds,
            "points": kiosk_user.points_balance,
            "last_seen_at": kiosk_user.last_seen_at.isoformat(),
        })

    return JsonResponse({
        "ok": True,
        "connected_count": len(client_rows),
        "active_access_count": active_access_count,
        "users": client_rows,
    })
