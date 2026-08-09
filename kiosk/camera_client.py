from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .ml_classifier import classify_bottle


MAX_CAMERA_IMAGE_BYTES = 5 * 1024 * 1024


class CameraUnavailableError(RuntimeError):
    """Raised when Django cannot obtain an image from the camera."""


def capture_camera_frame():
    camera_url = settings.ESP32_CAM_CAPTURE_URL

    if not camera_url:
        raise CameraUnavailableError(
            "ESP32_CAM_CAPTURE_URL is not configured."
        )

    request = Request(
        camera_url,
        headers={
            "User-Agent": "TrashToTech-Django/1.0",
        },
    )

    try:
        with urlopen(
            request,
            timeout=settings.ESP32_CAM_TIMEOUT_SECONDS,
        ) as response:
            content_type = response.headers.get(
                "Content-Type",
                "",
            ).lower()

            if not content_type.startswith("image/"):
                raise CameraUnavailableError(
                    "ESP32-CAM did not return an image."
                )

            image_data = response.read(
                MAX_CAMERA_IMAGE_BYTES + 1
            )

    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
    ) as error:
        raise CameraUnavailableError(
            "Could not contact the ESP32-CAM."
        ) from error

    if not image_data:
        raise CameraUnavailableError(
            "ESP32-CAM returned an empty image."
        )

    if len(image_data) > MAX_CAMERA_IMAGE_BYTES:
        raise CameraUnavailableError(
            "ESP32-CAM image was too large."
        )

    return BytesIO(image_data)


def classify_camera_frame():
    image_source = capture_camera_frame()
    return classify_bottle(image_source)
