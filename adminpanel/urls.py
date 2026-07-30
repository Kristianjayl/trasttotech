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
    path("about/", views.about, name="staff_about"),
    path("privacy/", views.privacy_policy, name="staff_privacy"),
    path("users/add/", views.user_create, name="staff_user_create"),
    path("users/<int:user_id>/edit/", views.user_edit, name="staff_user_edit"),
    path("users/<int:user_id>/delete/", views.user_delete, name="staff_user_delete"),
]