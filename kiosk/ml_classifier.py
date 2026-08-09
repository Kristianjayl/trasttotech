from functools import lru_cache
from pathlib import Path
from threading import Lock

import numpy as np
import tensorflow as tf
from PIL import Image, ImageOps


MODEL_FOLDER = Path(__file__).resolve().parent / "ml_models"
MODEL_PATH = MODEL_FOLDER / "model_unquant.tflite"
LABELS_PATH = MODEL_FOLDER / "labels.txt"

CLEAN_CONFIDENCE_MINIMUM = 0.80


@lru_cache(maxsize=1)
def load_bottle_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

    if not LABELS_PATH.exists():
        raise FileNotFoundError(f"Labels not found: {LABELS_PATH}")

    interpreter = tf.lite.Interpreter(
        model_path=str(MODEL_PATH),
        num_threads=2,
    )

    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

    labels = []

    for line in LABELS_PATH.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = line.strip()

        if not line:
            continue

        _number, label = line.split(maxsplit=1)
        labels.append(label)

    return (
        interpreter,
        input_details,
        output_details,
        labels,
        Lock(),
    )


def classify_bottle(image_source):
    (
        interpreter,
        input_details,
        output_details,
        labels,
        interpreter_lock,
    ) = load_bottle_model()

    input_shape = input_details["shape"]

    image_height = int(input_shape[1])
    image_width = int(input_shape[2])

    with Image.open(image_source) as image:
        image = image.convert("RGB")

        image = ImageOps.fit(
            image,
            (image_width, image_height),
            method=Image.Resampling.LANCZOS,
        )

        image_array = np.asarray(image, dtype=np.float32)

    # Teachable Machine floating-point models expect -1 to 1.
    normalized_image = (image_array / 127.5) - 1.0

    image_batch = np.expand_dims(
        normalized_image,
        axis=0,
    ).astype(input_details["dtype"])

    with interpreter_lock:
        interpreter.set_tensor(
            input_details["index"],
            image_batch,
        )

        interpreter.invoke()

        predictions = interpreter.get_tensor(
            output_details["index"]
        )[0]

    if len(predictions) != len(labels):
        raise ValueError(
            "The number of model results does not match labels.txt."
        )

    best_index = int(np.argmax(predictions))
    label = labels[best_index]
    confidence = float(predictions[best_index])

    is_clean = (
        label.lower() == "clean"
        and confidence >= CLEAN_CONFIDENCE_MINIMUM
    )

    confidence_percent = round(confidence * 100, 2)

    scores_percent = {
        labels[index]: round(float(score) * 100, 2)
        for index, score in enumerate(predictions)
    }

    return {
        "label": label,
        "confidence_percent": confidence_percent,
        "is_clean": is_clean,
        "scores_percent": scores_percent,
    }