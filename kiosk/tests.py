import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    BinStatus,
    BottleScan,
    KioskUser,
)


class BottleScanBinSafetyTests(TestCase):
    url = "/api/insert/start/"

    def set_bin_level(self, fill_percent):
        return BinStatus.objects.update_or_create(
            device_id="main-bin",
            defaults={
                "fill_percent": fill_percent,
                "is_full": fill_percent == BinStatus.FULL,
            },
        )[0]

    def test_full_bin_blocks_new_scan(self):
        self.set_bin_level(BinStatus.FULL)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"],
            "bin_full",
        )
        self.assertEqual(
            response.json()["fill_percent"],
            100,
        )
        self.assertEqual(
            BottleScan.objects.count(),
            0,
        )

    def test_non_full_levels_allow_scan(self):
        for level in (
            BinStatus.EMPTY,
            BinStatus.LOW,
            BinStatus.HALF,
        ):
            with self.subTest(fill_percent=level):
                BottleScan.objects.all().delete()
                self.set_bin_level(level)

                response = self.client.post(self.url)

                self.assertEqual(
                    response.status_code,
                    200,
                )
                self.assertEqual(
                    response.json()["status"],
                    BottleScan.WAITING,
                )
                self.assertEqual(
                    BottleScan.objects.count(),
                    1,
                )

    def test_full_bin_does_not_cancel_existing_scan(self):
        user = KioskUser.objects.create(
            device_id="existing-scan-user",
        )

        self.client.cookies["kiosk_uid"] = (
            user.device_id
        )

        existing_scan = BottleScan.objects.create(
            user=user,
            status=BottleScan.WAITING,
            expires_at=(
                timezone.now()
                + timedelta(seconds=60)
            ),
        )

        self.set_bin_level(BinStatus.FULL)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"],
            "bin_full",
        )

        existing_scan.refresh_from_db()

        self.assertEqual(
            existing_scan.status,
            BottleScan.WAITING,
        )
        self.assertEqual(
            BottleScan.objects.count(),
            1,
        )


@override_settings(ESP32_API_TOKEN="test-device-token")
class BinStatusApiTests(TestCase):
    url = "/api/device/bin-status/"

    def post_status(self, body, token="test-device-token"):
        return self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_DEVICE_TOKEN=token,
        )

    def test_accepts_all_supported_fill_levels(self):
        for level in (0, 25, 50, 100):
            response = self.post_status({
                "device_id": "main-bin",
                "fill_percent": level,
                "is_full": level == 100,
            })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["fill_percent"], level)

            saved = BinStatus.objects.get(device_id="main-bin")
            self.assertEqual(saved.fill_percent, level)
            self.assertEqual(saved.is_full, level == 100)

    def test_old_boolean_payload_remains_supported(self):
        response = self.post_status({
            "device_id": "main-bin",
            "is_full": True,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fill_percent"], 100)

    def test_rejects_unsupported_fill_level(self):
        response = self.post_status({
            "device_id": "main-bin",
            "fill_percent": 75,
            "is_full": False,
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "invalid_fill_percent",
        )

    def test_rejects_inconsistent_full_flag(self):
        response = self.post_status({
            "device_id": "main-bin",
            "fill_percent": 100,
            "is_full": False,
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "inconsistent_bin_status",
        )

    def test_rejects_wrong_device_token(self):
        response = self.post_status(
            {
                "device_id": "main-bin",
                "fill_percent": 25,
                "is_full": False,
            },
            token="wrong-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BinStatus.objects.exists())
