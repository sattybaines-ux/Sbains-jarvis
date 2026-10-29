"""Send the 'brief ready' push to the iPhone. Runs after GitHub Pages has deployed."""
import json

from .config import Config
from .publish import push

if __name__ == "__main__":
    cfg = Config()
    if not (cfg.vapid_private_key and cfg.push_subscriptions):
        print("Push skipped: VAPID_PRIVATE_KEY or PUSH_SUBSCRIPTIONS not set yet.")
    else:
        msg = json.loads((cfg.out_dir / "push.json").read_text())
        print(f"Notified {push(cfg.push_subscriptions, cfg.vapid_private_key, cfg.vapid_subject, msg['title'], msg['body'])} device(s).")
