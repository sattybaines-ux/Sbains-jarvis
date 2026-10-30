"""What the server has been doing, for the Health check in the app's Settings."""
import collections
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

_lines: collections.deque[str] = collections.deque(maxlen=80)
state: dict = {"started": time.time()}


def _now() -> str:
    return datetime.now(ZoneInfo(os.environ.get("TIMEZONE") or "America/Toronto")).strftime("%H:%M:%S")


def log(msg: str) -> None:
    line = f"{_now()} {msg}"
    _lines.append(line)
    sys.__stdout__.write(line + "\n")
    sys.__stdout__.flush()


def recent() -> list[str]:
    return list(_lines)


class _Tee:
    """Copies everything printed (e.g. the brief's step timings) into the recent log."""
    def __init__(self, stream):
        self.stream = stream

    def write(self, s):
        for line in s.splitlines():
            if line.strip():
                _lines.append(f"{_now()} {line}")
        return self.stream.write(s)

    def flush(self):
        self.stream.flush()


def capture_prints() -> None:
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)
