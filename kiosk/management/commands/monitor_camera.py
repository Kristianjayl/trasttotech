import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError

from kiosk.bottle_scans import complete_waiting_scan
from kiosk.camera_client import (
    CameraUnavailableError,
    classify_camera_frame,
)


def normalize_label(label):
    return (
        str(label)
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )


class Command(BaseCommand):
    help = (
        "Continuously monitor the ESP32-CAM "
        "for bottle events."
    )

    def handle(self, *args, **options):
        interval = settings.CAMERA_MONITOR_INTERVAL_SECONDS
        minimum_percent = settings.CAMERA_MONITOR_MINIMUM_PERCENT
        stable_frames_required = settings.CAMERA_MONITOR_STABLE_FRAMES

        candidate_label = None
        candidate_count = 0
        bottle_locked = False

        self.stdout.write(
            self.style.SUCCESS(
                "TrashToTech camera monitor started."
            )
        )
        self.stdout.write("Press Ctrl+C to stop.")

        try:
            while True:
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
                    if label_key == "no bottle":
                        if bottle_locked:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    "Object removed. Ready for the next scan."
                                )
                            )
                        bottle_locked = False

                    elif (
                        label_key in {"clean", "reject", "invalid"}
                        and not bottle_locked
                    ):
                        if label_key == "clean":
                            event_message = "EVENT: CLEAN BOTTLE"
                            event_style = self.style.SUCCESS
                        elif label_key == "reject":
                            event_message = "EVENT: REJECTED BOTTLE"
                            event_style = self.style.WARNING
                        else:
                            event_message = "EVENT: INVALID OBJECT"
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
                            # Do not lock the camera when nothing was saved.
                            # This lets a portal scan that starts while the
                            # object is still visible claim that object.
                            bottle_locked = False
                        else:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    "SAVED: "
                                    f"{saved_result['label']} | "
                                    f"{saved_result['status']} | "
                                    f"+{saved_result['points_awarded']} "
                                    "points | Balance: "
                                    f"{saved_result['new_balance']}"
                                )
                            )
                            # Lock only after a database scan was completed,
                            # preventing one bottle from earning points twice.
                            bottle_locked = True
                            self.stdout.write(
                                "Waiting for the object to be removed..."
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
