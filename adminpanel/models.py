from django.db import models
from django.contrib.auth.models import User


class StaffProfile(models.Model):
    ADMIN = "admin"
    SK = "sk"
    ROLE_CHOICES = [(ADMIN, "Admin"), (SK, "SK (Staff)")]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staffprofile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=SK)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"