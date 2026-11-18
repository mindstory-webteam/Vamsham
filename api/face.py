"""
Face scan: turn a camera photo into a face code (128 numbers) and compare codes.

Uses two free OpenCV models (no paid service, nothing leaves your server):
  - YuNet  finds the face in the photo
  - SFace  turns the face into a 128-number face code
Photos are only held in memory while the code is made; they are never saved.

Every photo goes through one check (analyse) before anything is decided:
  1. Find the faces. If the face looks sideways or upside down — some phones send the photo turned,
     without saying so — the photo is also tried turned 90°, 180° and 270°, and the way up where the
     face is clearest wins. (A sideways face was found, but its face code was useless: "no match".)
  2. Exactly one clear face, close enough to the camera.
  3. Light: a face that is too dark gives an unreliable face code → "too_dark" (ask for light).
  4. Sharpness: a blurry face (phone moving) gives an unreliable face code → "blurry" (hold still).
Only a photo that passes all of these is used to make, or check, a face code. The live "detecting"
check (detect) uses the same rules, so the app scans only when a frame will really work.

Speed: the live check looks for the face on a small copy of the photo (320 px — about 5 ms, as sure
as at full size). The face code itself is made from a full-size look at the face (exactly as before, so
saved face codes keep matching), using the "which way up" answer from the live check — no second search.
An upright face's box is taller than wide; a sideways one's isn't — so the turn search only runs for
photos that really look turned (it used to run on almost every frame).
"""
import base64
import binascii
import threading

from django.conf import settings

YUNET = "face_detection_yunet_2023mar.onnx"
SFACE = "face_recognition_sface_2021dec.onnx"
MAX_SIDE = 640          # photos are made smaller first: faster, and plenty for a selfie
DETECT_SIDE = 320       # the live "where is the face" check runs on a copy this size (≈4× faster)
MIN_SIDE = 320          # very small photos are made bigger, so a face in them can still be found
DET_SCORE = 0.8         # how sure YuNet must be that it is a face
UPRIGHT_SCORE = 0.93    # this sure → upright, no question
UPRIGHT_SHAPE = 1.12    # face box this much taller than wide (and DET_SCORE sure) → upright too
TURN_GAIN = 0.02        # a turned photo must be at least this much clearer to be used
MIN_FACE = 0.16         # face must be at least this part of the photo's short side ("come closer")
SECOND_FACE = 0.45      # another face this big (vs. the main face) means two people in the picture
MIN_LIGHT = 45          # average brightness of the face (0–255) below which it's too dark
MIN_SHARP = 16.0        # sharpness of the face below which it's too blurry

MESSAGES = {
    "no_face": "We couldn't see a face. Look straight at the camera in good light.",
    "many_faces": "More than one face is in the picture. Only one person, please.",
    "too_far": "Come a little closer to the camera.",
    "too_dark": "It's too dark to see the face. Turn towards a light.",
    "blurry": "The picture is blurry. Hold the phone still.",
}


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
            _models["det"] = cv2.FaceDetectorYN.create(str(d / YUNET), "", (320, 320), DET_SCORE, 0.3, 5000)
            _models["rec"] = cv2.FaceRecognizerSF.create(str(d / SFACE), "")
            if getattr(settings, "FACE_CV_THREADS", None):
                cv2.setNumThreads(int(settings.FACE_CV_THREADS))  # e.g. 1 per worker on a small server
            # each way a photo can be turned, and how to turn it back upright
            _models["turns"] = [
                (90, cv2.ROTATE_90_COUNTERCLOCKWISE),
                (270, cv2.ROTATE_90_CLOCKWISE),
                (180, cv2.ROTATE_180),
            ]
    return _models["cv2"], _models["det"], _models["rec"]


def available():
    try:
        _load()
        return True
    except (FaceError, ImportError):
        return False


def decode_image(data):
    """base64 (optionally a data: URL) or raw bytes → OpenCV image (EXIF rotation applied when present)."""
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
    return _fit(img)


def _fit(img):
    """Big photos smaller (faster), tiny ones bigger (so the face can still be found)."""
    cv2 = _models["cv2"]
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    elif max(h, w) < MIN_SIDE:
        s = MIN_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_CUBIC)
    return img


def _as_image(image):
    return _fit(image) if hasattr(image, "shape") else decode_image(image)


def _faces(img):
    """YuNet faces in this photo, biggest first (rows: x, y, w, h, 5 landmarks, score). Call under _lock."""
    det = _models["det"]
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, found = det.detect(img)
    if found is None:
        return []
    return sorted(found, key=lambda f: float(f[2] * f[3]), reverse=True)


def _small(img):
    """A copy at most DETECT_SIDE px, and the factor to scale its boxes back to `img`."""
    cv2 = _models["cv2"]
    h, w = img.shape[:2]
    s = min(1.0, DETECT_SIDE / max(h, w))
    if s >= 1.0:
        return img, 1.0
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA), 1.0 / s


def _looks_upright(faces):
    if not faces:
        return False
    main = faces[0]
    score = float(main[14])
    return score >= UPRIGHT_SCORE or (score >= DET_SCORE and float(main[3]) >= UPRIGHT_SHAPE * float(main[2]))


def _upright(img):
    """Find the faces on a small copy; if the face doesn't look upright, also try the copy turned and keep
    the way up where the face is clearest. → (photo turned upright, faces in its coordinates, degrees).
    Call under _lock."""
    cv2 = _models["cv2"]
    small, back = _small(img)
    faces = _faces(small)
    turned, how = 0, None
    if not _looks_upright(faces):
        best = max((float(f[14]) for f in faces), default=0.0)
        for degrees, rot in _models["turns"]:
            f = _faces(cv2.rotate(small, rot))
            sc = max((float(x[14]) for x in f), default=0.0)
            if sc > best + TURN_GAIN:
                best, faces, turned, how = sc, f, degrees, rot
    if how is not None:
        img = cv2.rotate(img, how)
    if back != 1.0:
        faces = [_scaled(f, back) for f in faces]
    return img, faces, turned


def _scaled(f, k):
    g = f.copy()
    g[:14] *= k  # box and landmarks; the score stays
    return g


def _quality(img, face):
    """(brightness 0–255, sharpness) of the face area."""
    cv2 = _models["cv2"]
    import numpy as np

    h, w = img.shape[:2]
    x, y, fw, fh = (int(round(float(v))) for v in face[:4])
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + fw, w), min(y + fh, h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0, 0.0
    crop = cv2.resize(img[y0:y1, x0:x1], (128, 128), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    light = float(gray.mean())
    # sharpness after evening out the contrast, so a dim but sharp face isn't called blurry
    norm = (gray - gray.mean()) / (float(gray.std()) + 1e-3) * 48.0
    sharp = float(cv2.Laplacian(norm, cv2.CV_32F).var())
    return light, sharp


def _verdict(img, faces):
    """(code, light, sharp) — code None when the main face is good enough to use."""
    h, w = img.shape[:2]
    if not faces:
        # a dark picture with something in it = a dark room. A flat black one is the camera still
        # starting up (or covered) — that's just "no face yet", not "too dark".
        dark_room = float(img.mean()) < MIN_LIGHT and float(img.std()) > 4.0
        return ("too_dark" if dark_room else "no_face"), 0.0, 0.0
    main = faces[0]
    if len(faces) > 1 and float(faces[1][2] * faces[1][3]) > SECOND_FACE * float(main[2] * main[3]):
        return "many_faces", 0.0, 0.0
    if min(float(main[2]), float(main[3])) < MIN_FACE * min(w, h):
        return "too_far", 0.0, 0.0
    light, sharp = _quality(img, main)
    if light < MIN_LIGHT:
        return "too_dark", light, sharp
    if sharp < MIN_SHARP:
        return "blurry", light, sharp
    return None, light, sharp


def analyse(image):
    """The one check every photo goes through. → dict:
         img    the photo, turned upright if it came in sideways
         faces  faces found in it, biggest first (the first is "the" face)
         turned 0 / 90 / 180 / 270 — how far the photo was turned to make it upright
         code   None when the face is good to use, else no_face / many_faces / too_far / too_dark / blurry
         light, sharp   how bright and how sharp the face is
    """
    img = _as_image(image)
    _load()
    with _lock:  # OpenCV DNN objects aren't thread-safe
        img, faces, turned = _upright(img)
    code, light, sharp = _verdict(img, faces)
    return {"img": img, "faces": faces, "turned": turned, "code": code, "light": light, "sharp": sharp}


def _need_good(a):
    if a["code"]:
        raise FaceError(a["code"], MESSAGES[a["code"]])
    return a["faces"][0]


def seen_of(a):
    """The live-check answer for an analysed photo (what detect() returns)."""
    img = a["img"]
    h, w = img.shape[:2]
    code = a["code"]
    return {
        "width": w, "height": h, "ok": code is None, "code": code or "ok",
        "message": MESSAGES.get(code, "Face found."), "turned": a["turned"],
        "light": round(a["light"], 1), "sharp": round(a["sharp"], 1),
        "faces": [{"x": round(float(f[0]) / w, 4), "y": round(float(f[1]) / h, 4), "w": round(float(f[2]) / w, 4),
                   "h": round(float(f[3]) / h, 4), "score": round(float(f[14]), 3)} for f in a["faces"][:4]],
    }


def code_of(a):
    """Face code from an analysed photo that passed. The face is looked at once more at full size (its
    eyes, nose and mouth as precisely as the saved face codes were made), without any turn search."""
    _, _, rec = _load()
    face = _need_good(a)
    with _lock:
        full = _faces(a["img"])
        if full:
            # the full-size face that is the same face the quick look found
            cx, cy = float(face[0] + face[2] / 2), float(face[1] + face[3] / 2)
            near = [f for f in full if f[0] <= cx <= f[0] + f[2] and f[1] <= cy <= f[1] + f[3]]
            face = near[0] if near else face
        feat = rec.feature(rec.alignCrop(a["img"], face))
    v = feat.flatten().astype(float)
    n = float((v ** 2).sum()) ** 0.5 or 1.0
    return [round(x / n, 6) for x in v]


def detect(image):
    """Where are the faces? For the live "detecting" box while scanning — cheap, no face code made.
    Boxes are fractions (0..1) of the upright photo; width/height are the upright photo's size.
    → {width, height, faces: [{x, y, w, h, score}], ok, code, message, turned, light, sharp}"""
    return seen_of(analyse(image))


def portrait(image, size=512):
    """A square, upright profile picture cut around the face (head and a little of the shoulders) → JPEG bytes."""
    cv2, _, _ = _load()
    a = analyse(image)
    if a["code"] in ("no_face", "many_faces"):  # a slightly dark or soft photo is still fine as a picture
        raise FaceError(a["code"], MESSAGES[a["code"]])
    img = a["img"]
    h, w = img.shape[:2]
    x, y, fw, fh = (float(v) for v in a["faces"][0][:4])
    side = min(max(fw, fh) * 2.2, w, h)
    cx, cy = x + fw / 2, y + fh / 2 + fh * 0.12  # a little lower: room for the chin and shoulders
    left = int(min(max(cx - side / 2, 0), w - side))
    top = int(min(max(cy - side / 2, 0), h - side))
    crop = img[top:top + int(side), left:left + int(side)]
    crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA if side > size else cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise FaceError("bad_image", "That photo couldn't be saved.")
    return buf.tobytes()


def embed(image):
    """Photo → face code (list of 128 floats). Raises FaceError unless there is exactly one clear,
    bright-enough, sharp face (the photo is turned upright first if needed)."""
    return code_of(analyse(image))


def similarity(a, b):
    """Cosine similarity of two face codes (1.0 = same picture, ~0.2 = different people)."""
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def best_match(code, saved):
    return max((similarity(code, s) for s in saved), default=0.0)
