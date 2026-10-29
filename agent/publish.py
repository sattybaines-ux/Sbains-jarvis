"""Encrypt the brief for the iPhone app, and send the push notification.

The site is public (GitHub Pages), so the brief is encrypted with AES-256-GCM using a key
derived from BRIEF_PASSPHRASE (PBKDF2-SHA256). Only a phone that knows the passphrase can read it.
"""
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pywebpush import WebPushException, webpush

ITERATIONS = 600_000
b64 = lambda b: base64.b64encode(b).decode()


def encrypt(payload: dict, passphrase: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(), None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def write_site(site_dir: Path, app_dir: Path, payload: dict, passphrase: str, vapid_public_key: str) -> None:
    import shutil
    if site_dir.exists():
        shutil.rmtree(site_dir)
    shutil.copytree(app_dir, site_dir)
    (site_dir / "config.js").write_text(f"window.JARVIS_CONFIG = {json.dumps({'vapidPublicKey': vapid_public_key})};\n")
    (site_dir / "data").mkdir(exist_ok=True)
    (site_dir / "data" / "latest.json").write_text(json.dumps(encrypt(payload, passphrase)))


def push(subscriptions_json: str, vapid_private_key: str, subject: str, title: str, body: str) -> int:
    subs = json.loads(subscriptions_json)
    subs = subs if isinstance(subs, list) else [subs]
    sent = 0
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=json.dumps({"title": title, "body": body}),
                    vapid_private_key=vapid_private_key, vapid_claims={"sub": subject}, ttl=6 * 3600)
            sent += 1
        except WebPushException as e:
            print(f"push failed: {e}")
    if not sent:
        raise RuntimeError("No push subscription accepted the notification.")
    return sent
