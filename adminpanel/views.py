from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta

from .decorators import role_required
from .models import StaffProfile
from kiosk.models import KioskUser, Transaction, Voucher, BottleRate, WifiRate


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
    total_kg = Transaction.objects.filter(type=Transaction.DEPOSIT).aggregate(
        total=Sum("weight_kg"))["total"] or 0
    points_issued = Transaction.objects.filter(type=Transaction.DEPOSIT).aggregate(
        total=Sum("points_delta"))["total"] or 0
    wifi_sessions = Transaction.objects.filter(type=Transaction.WIFI_REDEEM).count()
    active_users = KioskUser.objects.filter(points_balance__gt=0).count()
    internet_minutes = Transaction.objects.filter(type=Transaction.WIFI_REDEEM).aggregate(
        total=Sum("wifi_minutes"))["total"] or 0

    recent_transactions = Transaction.objects.select_related("user").order_by("-created_at")[:10]

    return render(request, "adminpanel/overview.html", {
        "total_pieces": total_pieces,
        "total_kg": round(total_kg, 2),
        "points_issued": points_issued,
        "wifi_sessions": wifi_sessions,
        "active_users": active_users,
        "internet_hours": round(internet_minutes / 60, 1),
        "recent_transactions": recent_transactions,
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
    if request.method == "POST":
        bottle_rate = BottleRate.objects.first()
        bottle_rate.points_per_bottle = int(request.POST.get("points_per_bottle"))
        bottle_rate.save()

        for wr in WifiRate.objects.all():
            new_val = request.POST.get(f"wifi_points_{wr.id}")
            if new_val:
                wr.points = int(new_val)
                wr.save()
        return redirect("staff_rates")

    return render(request, "adminpanel/rates.html", {
        "bottle_rate": BottleRate.objects.first(),
        "wifi_rates": WifiRate.objects.order_by("points"),
    })


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
        username = request.POST.get("username")
        password = request.POST.get("password")
        role = request.POST.get("role")
        if User.objects.filter(username=username).exists():
            return render(request, "adminpanel/staff_account_form.html", {
                "mode": "create", "error": "That username already exists."
            })
        new_user = User.objects.create_user(username=username, password=password)
        StaffProfile.objects.create(user=new_user, role=role)
        return redirect("staff_accounts_list")
    return render(request, "adminpanel/staff_account_form.html", {"mode": "create"})


@role_required('admin')
def staff_account_edit(request, profile_id):
    profile = get_object_or_404(StaffProfile, id=profile_id)
    if request.method == "POST":
        profile.role = request.POST.get("role")
        profile.save()
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