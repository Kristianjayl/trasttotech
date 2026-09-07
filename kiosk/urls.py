from django.urls import path
from . import views

urlpatterns = [
    path("", views.portal, name="portal"),
    path("api/status/", views.api_status, name="api_status"),
    path("api/insert/start/", views.api_insert_start, name="api_insert_start"),
    path("api/insert/poll/", views.api_insert_poll, name="api_insert_poll"),
    path("api/insert/confirm/", views.api_insert_confirm, name="api_insert_confirm"),
    path("api/insert/cancel/", views.api_insert_cancel, name="api_insert_cancel"),
    path("api/redeem/wifi/", views.api_redeem_wifi, name="api_redeem_wifi"),
    path("api/pause/", views.api_pause_toggle, name="api_pause_toggle"),
    path("api/voucher/generate/", views.api_voucher_generate, name="api_voucher_generate"),
    path("api/voucher/submit/", views.api_voucher_submit, name="api_voucher_submit"),
    path(
    "api/classify-bottle/",
    views.api_classify_bottle,
    name="api_classify_bottle",
    ),
    path(
    "api/device/ping/",
    views.api_device_ping,
    name="api_device_ping",
    ),
    path(
    "api/device/scan-status/",
    views.api_device_scan_status,
    name="api_device_scan_status",
    ),
    path(
    "api/device/bin-status/",
    views.api_bin_status,
    name="api_bin_status",
    ),
]