import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError
from django.utils import timezone

from kiosk.bottle_scans import complete_waiting_scan
from kiosk.camera_client import (
    CameraUnavailableError,
    capture_camera_frame,
    classify_camera_frame,
)
from kiosk.ml_classifier import load_bottle_model
from kiosk.models import BottleScan


def normalize_label(label):
    return (
        str(label)
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )


def has_active_waiting_scan():
    """Return True only while a portal user has requested a scan."""
    now = timezone.now()

    BottleScan.objects.filter(
        status=BottleScan.WAITING,
        expires_at__lte=now,
    ).update(
        status=BottleScan.EXPIRED,
        completed_at=now,
    )

    return BottleScan.objects.filter(
        status=BottleScan.WAITING,
        expires_at__gt=now,
    ).exists()


class Command(BaseCommand):
    help = (
        "Wait for a portal scan request, then monitor the ESP32-CAM "
        "for one recycling event."
    )

    def handle(self, *args, **options):
        interval = settings.CAMERA_MONITOR_INTERVAL_SECONDS
        minimum_percent = settings.CAMERA_MONITOR_MINIMUM_PERCENT
        stable_frames_required = settings.CAMERA_MONITOR_STABLE_FRAMES

        candidate_label = None
        candidate_count = 0

        # Load TensorFlow and the TFLite model now, while the monitor is
        # idle. Otherwise the first client who presses Insert Item has to
        # wait for the model to load before their scan can begin.
        self.stdout.write("Loading item-classification model...")
        try:
            load_bottle_model()
        except (OSError, ValueError, RuntimeError) as error:
            self.stderr.write(
                self.style.ERROR(
                    "Could not load the item-classification model: "
                    f"{error}"
                )
            )
            return

        # Verify that the ESP32-CAM can be reached before reporting that the
        # monitor is ready. This retrieves one image but does not classify an
        # item or save a scan result.
        try:
            capture_camera_frame()
        except CameraUnavailableError as error:
            self.stderr.write(
                self.style.ERROR(
                    "Camera unavailable. The monitor was not started: "
                    f"{error}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "ESP32-CAM connection verified. "
                "Waiting for Insert Item requests."
            )
        )
        self.stdout.write("Press Ctrl+C to stop.")

        try:
            while True:
                # Keep the camera idle until a portal client explicitly
                # presses Insert Item. This avoids unnecessary captures and
                # classification while nobody is using the machine.
                if not has_active_waiting_scan():
                    candidate_label = None
                    candidate_count = 0
                    time.sleep(min(interval, 0.5))
                    continue

                try:
                    result = classify_camera_frame()
                except CameraUnavailableError as error:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Camera unavailable: {error}"
                        )
                    )
                    time.sleep(3)
                    continue
                except (OSError, ValueError) as error:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Frame error: {error}"
                        )
                    )
                    time.sleep(3)
                    continue

                label = result["label"]
                label_key = normalize_label(label)
                confidence = result["confidence_percent"]

                if confidence < minimum_percent:
                    candidate_label = None
                    candidate_count = 0
                    self.stdout.write(
                        f"Uncertain: {label} ({confidence:.2f}%)"
                    )
                    time.sleep(interval)
                    continue

                if label_key == candidate_label:
                    candidate_count += 1
                else:
                    candidate_label = label_key
                    candidate_count = 1

                self.stdout.write(
                    f"Watching: {label} ({confidence:.2f}%) "
                    f"[{candidate_count}/{stable_frames_required}]"
                )

                if candidate_count >= stable_frames_required:
                    if label_key == "no item":
                        self.stdout.write("No item detected yet.")

                    elif (
                        label_key in {
                            "plastic bottle",
                            "tin can",
                            "other object",
                        }
                    ):
                        if label_key == "plastic bottle":
                            event_message = "EVENT: PLASTIC BOTTLE"
                            event_style = self.style.SUCCESS
                        elif label_key == "tin can":
                            event_message = "EVENT: TIN CAN"
                            event_style = self.style.SUCCESS
                        else:
                            event_message = "EVENT: OTHER OBJECT"
                            event_style = self.style.WARNING

                        self.stdout.write(
                            event_style(
                                f"{event_message} ({confidence:.2f}%)"
                            )
                        )

                        try:
                            saved_result = complete_waiting_scan(
                                label,
                                confidence,
                            )
                        except (DatabaseError, RuntimeError) as error:
                            self.stderr.write(
                                self.style.ERROR(
                                    "Could not save scan result: "
                                    f"{error}"
                                )
                            )
                            candidate_count = 0
                            time.sleep(interval)
                            continue

                        if saved_result is None:
                            self.stdout.write(
                                self.style.WARNING(
                                    "No active portal scan. "
                                    "Waiting for the portal to start one."
                                )
                            )
                        else:
                            saved_style = (
                                self.style.SUCCESS
                                if saved_result["status"] == "accepted"
                                else self.style.WARNING
                            )

                            self.stdout.write(
                                saved_style(
                                    "SAVED: "
                                    f"{saved_result['label']} | "
                                    f"{saved_result['status']} | "
                                    f"+{saved_result['points_awarded']} "
                                    "points | Balance: "
                                    f"{saved_result['new_balance']}"
                                )
                            )

                            self.stdout.write(
                                "Scan complete. Waiting for the next "
                                "Insert Item request."
                            )

                    candidate_count = 0

                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Camera monitor stopped."
                )
            )


