from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("staff/", include("adminpanel.urls")),
    path("", include("kiosk.urls")),
]