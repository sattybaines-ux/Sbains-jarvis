"""Deterministic calendar checks: dedupe across accounts, overlaps, and 90+ minute focus gaps."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def localize(events: list[dict], tz: ZoneInfo) -> list[dict]:
    seen, out = set(), []
    for e in events:
        if e["all_day"]:
            e["start_local"], e["end_local"] = e["start"], e["end"]
        else:
            e["start_local"] = datetime.fromisoformat(e["start"]).astimezone(tz).isoformat(timespec="minutes")
            e["end_local"] = datetime.fromisoformat(e["end"]).astimezone(tz).isoformat(timespec="minutes")
        key = (e["title"].strip().lower(), e["start_local"], e["end_local"])
        if key in seen:  # same meeting on both calendars
            continue
        seen.add(key)
        out.append(e)
    return sorted(out, key=lambda e: e["start_local"])


def conflicts(events: list[dict]) -> list[tuple[str, str]]:
    timed = [e for e in events if not e["all_day"] and not e["free"]]
    pairs = []
    for i, a in enumerate(timed):
        for b in timed[i + 1:]:
            if b["start_local"] < a["end_local"] and a["start_local"] < b["end_local"]:
                pairs.append((a["title"], b["title"]))
    return pairs


def focus_gaps(events: list[dict], day: datetime, tz: ZoneInfo, minutes: int = 90) -> list[str]:
    # Gaps only count from now on, so an afternoon refresh doesn't offer focus time that has passed.
    start = max(datetime.combine(day.date(), time(8, 0), tz), day.replace(second=0, microsecond=0))
    end = datetime.combine(day.date(), time(17, 0), tz)
    busy = sorted(
        (max(datetime.fromisoformat(e["start_local"]), start), min(datetime.fromisoformat(e["end_local"]), end))
        for e in events if not e["all_day"] and not e["free"]
    )
    gaps, cursor = [], start
    for s, f in busy:
        if s - cursor >= timedelta(minutes=minutes):
            gaps.append(f"{cursor:%H:%M}-{s:%H:%M}")
        cursor = max(cursor, f)
    if end - cursor >= timedelta(minutes=minutes):
        gaps.append(f"{cursor:%H:%M}-{end:%H:%M}")
    return gaps
