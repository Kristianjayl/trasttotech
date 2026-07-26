from django.db import models


class KioskUser(models.Model):
    """
    A client identified by device.
    NOTE: A real deployment reads the MAC address from the router/firmware.
    A plain Django view can't read a device's real MAC -- browsers don't
    expose that. We use a cookie-based id instead, formatted to look like
    a MAC for display. Swap this for real router data once hardware is wired in.
    """
    device_id = models.CharField(max_length=64, unique=True)
    points_balance = models.IntegerField(default=0)
    total_kg = models.FloatField(default=0)
    remaining_seconds = models.IntegerField(default=0)
    paused = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    session_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def mac_display(self):
        h = self.device_id.replace("-", "")[:12].upper().ljust(12, "0")
        return ":".join(h[i:i + 2] for i in range(0, 12, 2))


class PlasticRate(models.Model):
    weight_kg = models.FloatField()
    points = models.IntegerField()

    class Meta:
        ordering = ["weight_kg"]


class WifiRate(models.Model):
    points = models.IntegerField()
    minutes = models.IntegerField()
    label = models.CharField(max_length=64)

    class Meta:
        ordering = ["points"]


class Transaction(models.Model):
    DEPOSIT = "deposit"
    WIFI_REDEEM = "wifi_redeem"
    VOUCHER = "voucher"
    TYPE_CHOICES = [(DEPOSIT, "Deposit"), (WIFI_REDEEM, "WiFi Redeem"), (VOUCHER, "Voucher")]

    user = models.ForeignKey(KioskUser, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    weight_kg = models.FloatField(null=True, blank=True)
    points_delta = models.IntegerField()
    wifi_minutes = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Voucher(models.Model):
    PENDING, REDEEMED, INVALID = "pending", "redeemed", "invalid"
    STATUS_CHOICES = [(PENDING, "Pending"), (REDEEMED, "Redeemed"), (INVALID, "Invalid")]

    code = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(KioskUser, on_delete=models.CASCADE, related_name="vouchers")
    points_used = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    generated_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)