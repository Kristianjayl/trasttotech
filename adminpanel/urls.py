from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [

    # ===================== AUTH =====================
    path("login/", views.StaffLoginView.as_view(), name="staff_login"),
    path("logout/", LogoutView.as_view(), name="staff_logout"),

    # ===================== DASHBOARD =====================
    path("", views.overview, name="staff_overview"),

    # ===================== CLIENT USERS (kiosk customers) =====================
    # These manage the people using the vending machine -- their points,
    # bottle counts, etc. Different from Staff Accounts below.
    path("users/", views.users_list, name="staff_users"),
    path("users/add/", views.user_create, name="staff_user_create"),
    path("users/<int:user_id>/edit/", views.user_edit, name="staff_user_edit"),
    path("users/<int:user_id>/delete/", views.user_delete, name="staff_user_delete"),

    # ===================== TRANSACTIONS & REWARDS =====================
    path("transactions/", views.transactions_list, name="staff_transactions"),
    path("rewards/", views.rewards, name="staff_rewards"),

    # ===================== ADMIN-ONLY: RATES & SETTINGS =====================
    # Restricted via @role_required('admin') in views.py -- SK cannot access these.
    path("rates/", views.rates, name="staff_rates"),
    path("settings/", views.settings_page, name="staff_settings"),
    path("reports/", views.reports, name="staff_reports"),

    # ===================== ADMIN-ONLY: STAFF ACCOUNTS (Admin/SK logins) =====================
    # These manage YOUR team's dashboard logins -- who's Admin, who's SK.
    # Different from Client Users above. Also restricted to Admin only.
    path("accounts/", views.staff_accounts_list, name="staff_accounts_list"),
    path("accounts/add/", views.staff_account_create, name="staff_account_create"),
    path("accounts/<int:profile_id>/edit/", views.staff_account_edit, name="staff_account_edit"),
    path("accounts/<int:profile_id>/delete/", views.staff_account_delete, name="staff_account_delete"),

    # ===================== LOGS =====================
    path("logs/", views.logs, name="staff_logs"),

    # ===================== FOOTER PAGES =====================
    path("about/", views.about, name="staff_about"),
    path("privacy/", views.privacy_policy, name="staff_privacy"),

    # ===================== API's =====================

    path(
    "api/bin-status/",
    views.bin_status_live,
    name="staff_bin_status_live",
    ),
    path(
        "api/bottle-scan/",
        views.bottle_scan_live,
        name="staff_bottle_scan_live",
    ),
    path(
        "api/wifi-users/",
        views.wifi_users_live,
        name="staff_wifi_users_live",
    ),
]
