import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    BinStatus,
    BottleRate,
    BottleScan,
    KioskUser,
    MetalStatus,
    TinCanRate,
    Transaction,
)

from .bottle_scans import complete_waiting_scan


class PlasticBottleAcceptanceTests(TestCase):
    def setUp(self):
        self.user = KioskUser.objects.create(
            device_id="plastic-bottle-test-user",
        )
        BottleRate.objects.create(points_per_bottle=5)

    def start_waiting_scan(self):
        return BottleScan.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(seconds=60),
        )

    def test_plastic_bottle_is_accepted(self):
        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "plastic_bottle",
            99.0,
        )

        scan.refresh_from_db()
        self.user.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.ACCEPTED)
        self.assertEqual(scan.status, BottleScan.ACCEPTED)
        self.assertEqual(transaction.condition, Transaction.CLEAN)
        # test_plastic_bottle_is_accepted
        self.assertEqual(
            transaction.item_type,
            Transaction.PLASTIC_BOTTLE,
        )
        self.assertEqual(transaction.points_delta, 5)
        self.assertEqual(self.user.points_balance, 5)

    def test_plastic_bottle_is_rejected_when_plastic_bin_is_full(self):
        BinStatus.objects.create(
            device_id="plastic-bin",
            fill_percent=BinStatus.FULL,
            is_full=True,
        )

        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "plastic_bottle",
            99.0,
        )

        scan.refresh_from_db()
        self.user.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.REJECTED)
        self.assertEqual(
            result["rejection_reason"],
            BottleScan.PLASTIC_BIN_FULL,
        )
        self.assertEqual(
            scan.rejection_reason,
            BottleScan.PLASTIC_BIN_FULL,
        )
        self.assertEqual(transaction.points_delta, 0)
        self.assertEqual(transaction.pieces, 0)
        self.assertEqual(
            transaction.item_type,
            Transaction.PLASTIC_BOTTLE,
        )
        self.assertEqual(self.user.points_balance, 0)

    def test_tin_can_is_rejected_when_tin_can_bin_is_full(self):
        TinCanRate.objects.create(
            points_per_tin_can=5,
        )
        MetalStatus.objects.create(
            device_id="main-metal-sensor",
            metal_detected=True,
            light_value=800,
            last_detected_at=timezone.now(),
        )
        BinStatus.objects.create(
            device_id="tin-can-bin",
            fill_percent=BinStatus.FULL,
            is_full=True,
        )

        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "tin_can",
            99.0,
        )

        scan.refresh_from_db()
        self.user.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.REJECTED)
        self.assertEqual(
            result["rejection_reason"],
            BottleScan.TIN_CAN_BIN_FULL,
        )
        self.assertEqual(
            scan.rejection_reason,
            BottleScan.TIN_CAN_BIN_FULL,
        )
        self.assertEqual(transaction.points_delta, 0)
        self.assertEqual(transaction.pieces, 0)
        self.assertEqual(
            transaction.item_type,
            Transaction.TIN_CAN,
        )
        self.assertEqual(self.user.points_balance, 0)

    def test_tin_can_is_accepted_after_recent_metal_detection(self):
        TinCanRate.objects.create(
            points_per_tin_can=5,
        )
        MetalStatus.objects.create(
            device_id="main-metal-sensor",
            metal_detected=True,
            light_value=800,
            last_detected_at=timezone.now(),
        )

        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "tin_can",
            99.0,
        )

        scan.refresh_from_db()
        self.user.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.ACCEPTED)
        self.assertEqual(scan.status, BottleScan.ACCEPTED)
        self.assertEqual(transaction.condition, Transaction.CLEAN)
        # test_tin_can_is_accepted_after_recent_metal_detection
        self.assertEqual(
            transaction.item_type,
            Transaction.TIN_CAN,
        )

        self.assertEqual(transaction.points_delta, 5)
        self.assertEqual(transaction.pieces, 1)
        self.assertEqual(self.user.points_balance, 5)

    def test_tin_can_is_rejected_without_recent_metal_detection(self):
        TinCanRate.objects.create(
            points_per_tin_can=5,
        )
        MetalStatus.objects.create(
            device_id="main-metal-sensor",
            metal_detected=False,
            light_value=0,
            last_detected_at=None,
        )

        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "tin_can",
            99.0,
        )

        scan.refresh_from_db()
        self.user.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.REJECTED)
        self.assertEqual(scan.status, BottleScan.REJECTED)
        self.assertEqual(transaction.condition, Transaction.DIRTY)
        # test_tin_can_is_rejected_without_recent_metal_detection
        self.assertEqual(
            transaction.item_type,
            Transaction.TIN_CAN,
        )
        self.assertEqual(transaction.points_delta, 0)
        self.assertEqual(transaction.pieces, 0)
        self.assertEqual(self.user.points_balance, 0)

    def test_tin_can_is_rejected_when_metal_detection_is_stale(self):
        TinCanRate.objects.create(
            points_per_tin_can=10,
        )
        MetalStatus.objects.create(
            device_id="main-metal-sensor",
            metal_detected=True,
            light_value=800,
            last_detected_at=(
                timezone.now() - timedelta(seconds=11)
            ),
        )

        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "tin_can",
            99.0,
        )

        scan.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.REJECTED)
        self.assertEqual(scan.status, BottleScan.REJECTED)
        self.assertEqual(transaction.points_delta, 0)
        self.assertEqual(transaction.pieces, 0)
        # test_tin_can_is_rejected_when_metal_detection_is_stale
        self.assertEqual(
            transaction.item_type,
            Transaction.TIN_CAN,
        )

    def test_other_object_is_rejected(self):
        scan = self.start_waiting_scan()

        result = complete_waiting_scan(
            "other_object",
            99.0,
        )

        scan.refresh_from_db()
        self.user.refresh_from_db()
        transaction = Transaction.objects.get()

        self.assertEqual(result["status"], BottleScan.REJECTED)
        self.assertEqual(scan.status, BottleScan.REJECTED)
        self.assertEqual(transaction.points_delta, 0)
        self.assertEqual(transaction.pieces, 0)
        # test_other_object_is_rejected
        self.assertEqual(
            transaction.item_type,
            Transaction.OTHER_OBJECT,
        )
        self.assertEqual(self.user.points_balance, 0)


class BottleScanBinSafetyTests(TestCase):
    url = "/api/insert/start/"

    def set_bin_full(self, device_id, is_full):
        return BinStatus.objects.update_or_create(
            device_id=device_id,
            defaults={
                "fill_percent": (
                    BinStatus.FULL
                    if is_full
                    else BinStatus.EMPTY
                ),
                "is_full": is_full,
            },
        )[0]

    def test_both_full_bins_block_new_scan(self):
        self.set_bin_full("plastic-bin", True)
        self.set_bin_full("tin-can-bin", True)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"],
            "bin_full",
        )
        self.assertEqual(
            BottleScan.objects.count(),
            0,
        )

    def test_one_full_bin_allows_new_scan(self):
        self.set_bin_full("plastic-bin", True)
        self.set_bin_full("tin-can-bin", False)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["status"],
            BottleScan.WAITING,
        )
        self.assertEqual(
            BottleScan.objects.count(),
            1,
        )

    def test_full_bins_do_not_cancel_existing_scan(self):
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

        self.set_bin_full("plastic-bin", True)
        self.set_bin_full("tin-can-bin", True)

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

@override_settings(ESP32_API_TOKEN="test-device-token")
class MetalStatusApiTests(TestCase):
    url = "/api/device/metal-status/"

    def post_status(self, body, token="test-device-token"):
        return self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_DEVICE_TOKEN=token,
            HTTP_HOST="localhost",
        )

    def test_saves_detected_metal_status(self):
        response = self.post_status({
            "device_id": "main-metal-sensor",
            "metal_detected": True,
            "light_value": 2000,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["metal_detected"])
        self.assertEqual(response.json()["light_value"], 2000)

        saved = MetalStatus.objects.get(
            device_id="main-metal-sensor",
        )
        self.assertTrue(saved.metal_detected)
        self.assertEqual(saved.light_value, 2000)

    def test_rejects_wrong_device_token(self):
        response = self.post_status(
            {
                "device_id": "main-metal-sensor",
                "metal_detected": True,
                "light_value": 2000,
            },
            token="wrong-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(MetalStatus.objects.exists())
