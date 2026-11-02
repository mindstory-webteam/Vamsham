"""Create in-app notifications and send Expo push notifications."""
import json
import logging
import os
import urllib.request

from .models import DeviceToken, Notification

log = logging.getLogger("api")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def push_enabled():
    return os.environ.get("EXPO_PUSH", "1") == "1"


def notify(users, title, body="", kind="info", data=None):
    """Save a notification for each user and push it to their phones. Returns the count."""
    users = [u for u in users if u is not None]
    if not users:
        return 0
    Notification.objects.bulk_create([
        Notification(user=u, title=title, body=body, kind=kind, data=data or {}) for u in users
    ])
    if push_enabled():
        tokens = list(DeviceToken.objects.filter(user__in=users).values_list("token", flat=True))
        _send_expo(tokens, title, body, data or {})
    return len(users)


def _send_expo(tokens, title, body, data):
    for i in range(0, len(tokens), 100):  # Expo accepts up to 100 per request
        batch = [{"to": t, "title": title, "body": body, "data": data, "sound": "default"} for t in tokens[i:i + 100]]
        req = urllib.request.Request(
            EXPO_PUSH_URL, data=json.dumps(batch).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=8).read()
        except Exception as exc:
            log.warning("Expo push failed: %s", exc)
