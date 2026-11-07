"""python manage.py download_face_models — fetch the two free OpenCV face models into FACE_MODEL_DIR."""
import hashlib
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        BASE + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "face_recognition_sface_2021dec.onnx": (
        BASE + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}


class Command(BaseCommand):
    help = "Download the face scan models (YuNet + SFace, from OpenCV Zoo)."

    def handle(self, *args, **opts):
        d = settings.FACE_MODEL_DIR
        d.mkdir(parents=True, exist_ok=True)
        for name, (url, sha) in MODELS.items():
            path = d / name
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
                self.stdout.write(f"✓ {name} already there")
                continue
            self.stdout.write(f"Downloading {name} …")
            data = urllib.request.urlopen(url, timeout=120).read()
            if hashlib.sha256(data).hexdigest() != sha:
                raise CommandError(f"{name}: download looks wrong (checksum). Try again.")
            path.write_bytes(data)
            self.stdout.write(self.style.SUCCESS(f"✓ {name} ({len(data) // 1024} KB)"))
        self.stdout.write(self.style.SUCCESS("Face scan models ready."))
