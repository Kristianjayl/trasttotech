from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta

from kiosk.models import KioskUser, Transaction, Voucher, BottleRate, WifiRate

class StaffLoginView(LoginView):
    template_name = "adminpanel/login.html"


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


@login_required
def users_list(request):
    users = KioskUser.objects.order_by("-points_balance")
    return render(request, "adminpanel/users.html", {"users": users})


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


@login_required
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


@login_required
def settings_page(request):
    return render(request, "adminpanel/settings.html")


@login_required
def logs(request):
    # Reusing Transaction as the log source for now -- once hardware is
    # wired in, real error/maintenance events would also feed this,
    # ideally via a dedicated Log model. Fine as a placeholder for now.
    entries = Transaction.objects.select_related("user").order_by("-created_at")[:100]
    return render(request, "adminpanel/logs.html", {"entries": entries})