import time

from django.conf import settings
from django.core.management.base import BaseCommand

from kiosk.camera_client import (
    CameraUnavailableError,
    classify_camera_frame,
)


def normalize_label(label):
    return (
        label.strip()
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
        interval = (
            settings.CAMERA_MONITOR_INTERVAL_SECONDS
        )
        minimum_percent = (
            settings.CAMERA_MONITOR_MINIMUM_PERCENT
        )
        stable_frames_required = (
            settings.CAMERA_MONITOR_STABLE_FRAMES
        )

        candidate_label = None
        candidate_count = 0

        # Locked means a bottle was already detected.
        # The system must see No Bottle before counting again.
        bottle_locked = False

        self.stdout.write(
            self.style.SUCCESS(
                "TrashToTech camera monitor started."
            )
        )

        self.stdout.write(
            "Press Ctrl+C to stop."
        )

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
                        f"Uncertain: {label} "
                        f"({confidence:.2f}%)"
                    )

                    time.sleep(interval)
                    continue

                if label_key == candidate_label:
                    candidate_count += 1
                else:
                    candidate_label = label_key
                    candidate_count = 1

                self.stdout.write(
                    f"Watching: {label} "
                    f"({confidence:.2f}%) "
                    f"[{candidate_count}/"
                    f"{stable_frames_required}]"
                )

                if (
                    candidate_count
                    >= stable_frames_required
                ):
                    if label_key == "no bottle":
                        if bottle_locked:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    "Bottle removed. "
                                    "Ready for the next bottle."
                                )
                            )

                        bottle_locked = False

                    elif (
                        label_key in {"clean", "reject"}
                        and not bottle_locked
                    ):
                        if label_key == "clean":
                            self.stdout.write(
                                self.style.SUCCESS(
                                    "EVENT: CLEAN BOTTLE "
                                    f"({confidence:.2f}%)"
                                )
                            )
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    "EVENT: REJECTED BOTTLE "
                                    f"({confidence:.2f}%)"
                                )
                            )

                        bottle_locked = True

                        self.stdout.write(
                            "Waiting for the bottle "
                            "to be removed..."
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