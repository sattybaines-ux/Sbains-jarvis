"""Small JSON state kept on the server: the latest brief and the phone's push subscriptions."""
import json
import threading

from agent.config import ROOT

DIR = ROOT / "out"
_lock = threading.Lock()


def _read(name: str, default):
    f = DIR / name
    try:
        return json.loads(f.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(name: str, value) -> None:
    DIR.mkdir(exist_ok=True)
    tmp = DIR / (name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(DIR / name)


def latest_brief() -> dict | None:
    return _read("latest_brief.json", None)


def save_brief(payload: dict) -> None:
    with _lock:
        _write("latest_brief.json", payload)


def subscriptions() -> list[dict]:
    return _read("push_subscriptions.json", [])


def add_subscription(sub: dict) -> None:
    with _lock:
        subs = [s for s in subscriptions() if s.get("endpoint") != sub.get("endpoint")]
        _write("push_subscriptions.json", subs + [sub])
