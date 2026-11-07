"""
Face scan: turn a camera photo into a face code (128 numbers) and compare codes.

Uses two free OpenCV models (no paid service, nothing leaves your server):
  - YuNet  finds the face in the photo
  - SFace  turns the face into a 128-number face code
Photos are only held in memory while the code is made; they are never saved.
"""
import base64
import binascii
import threading

from django.conf import settings

YUNET = "face_detection_yunet_2023mar.onnx"
SFACE = "face_recognition_sface_2021dec.onnx"
MAX_SIDE = 640  # photos are made smaller first: faster, and plenty for a selfie


class FaceError(Exception):
    """Something is wrong with the photo. `code` is for the app, the message is for people."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


_lock = threading.Lock()
_models = {}


def _load():
    with _lock:
        if not _models:
            import cv2  # imported here so the rest of the API works even without OpenCV

            d = settings.FACE_MODEL_DIR
            if not (d / YUNET).exists() or not (d / SFACE).exists():
                raise FaceError("not_ready", "Face scan isn't set up on the server yet.")
            _models["cv2"] = cv2
            _models["det"] = cv2.FaceDetectorYN.create(str(d / YUNET), "", (320, 320), 0.8, 0.3, 5)
            _models["rec"] = cv2.FaceRecognizerSF.create(str(d / SFACE), "")
    return _models["cv2"], _models["det"], _models["rec"]


def available():
    try:
        _load()
        return True
    except (FaceError, ImportError):
        return False


def decode_image(data):
    """base64 (optionally a data: URL) or raw bytes → OpenCV image."""
    cv2, _, _ = _load()
    import numpy as np

    if isinstance(data, str):
        if data.startswith("data:"):
            data = data.split(",", 1)[-1]
        try:
            data = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError):
            raise FaceError("bad_image", "That photo couldn't be read. Please try again.")
    if not data:
        raise FaceError("bad_image", "No photo was received. Please try again.")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FaceError("bad_image", "That photo couldn't be read. Please try again.")
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def embed(image):
    """Photo → face code (list of 128 floats). Raises FaceError when there isn't exactly one clear face."""
    cv2, det, rec = _load()
    img = decode_image(image) if not hasattr(image, "shape") else image
    h, w = img.shape[:2]
    with _lock:  # OpenCV DNN objects aren't thread-safe
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is None or len(faces) == 0:
            raise FaceError("no_face", "We couldn't see a face. Look straight at the camera in good light.")
        big = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        if len(big) > 1 and big[1][2] * big[1][3] > 0.45 * big[0][2] * big[0][3]:
            raise FaceError("many_faces", "More than one face is in the picture. Only you, please.")
        face = big[0]
        if min(face[2], face[3]) < 0.16 * min(w, h):
            raise FaceError("too_far", "Come a little closer to the camera.")
        feat = rec.feature(rec.alignCrop(img, face))
    v = feat.flatten().astype(float)
    n = float((v ** 2).sum()) ** 0.5 or 1.0
    return [round(x / n, 6) for x in v]


def similarity(a, b):
    """Cosine similarity of two face codes (1.0 = same picture, ~0.2 = different people)."""
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def best_match(code, saved):
    return max((similarity(code, s) for s in saved), default=0.0)
