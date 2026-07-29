from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path("login/", views.StaffLoginView.as_view(), name="staff_login"),
    path("logout/", LogoutView.as_view(), name="staff_logout"),
    path("", views.overview, name="staff_overview"),
    path("users/", views.users_list, name="staff_users"),
    path("transactions/", views.transactions_list, name="staff_transactions"),
    path("rewards/", views.rewards, name="staff_rewards"),
    path("rates/", views.rates, name="staff_rates"),
    path("settings/", views.settings_page, name="staff_settings"),
    path("logs/", views.logs, name="staff_logs"),
]