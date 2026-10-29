"""Live connections to Outlook, Google and Notion, kept warm between requests."""
import threading
import time
from datetime import datetime, time as dtime, timedelta

from agent import calendar_math
from agent.config import Config

TTL = 40 * 60  # Microsoft access tokens last about an hour; rebuild well before that


class Accounts:
    def __init__(self, demo: bool = False):
        self.demo = demo
        self._cache: dict[str, tuple[float, object]] = {}
        self._locks = {k: threading.Lock() for k in ("Outlook", "Gmail", "Notion")}

    def _client(self, name: str):
        hit = self._cache.get(name)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
        cfg = Config()
        if name == "Outlook":
            from agent.sources.outlook import connect
            c = connect(cfg)
        elif name == "Gmail":
            if not cfg.google_refresh_token:
                raise RuntimeError("Google isn't connected.")
            from agent.sources.google import Google
            c = Google(cfg.google_client_id, cfg.google_client_secret, cfg.google_refresh_token)
        else:
            if not cfg.notion_token:
                raise RuntimeError("Notion isn't connected.")
            from agent.sources.notion import Notion
            c = Notion(cfg.notion_token)
        self._cache[name] = (time.monotonic(), c)
        return c

    def use(self, name: str, fn):
        """Runs fn(client) for one account. The Google client isn't thread-safe, so each account is serialized."""
        with self._locks[name]:
            return fn(self._client(name))

    def connected(self) -> list[str]:
        cfg = Config()
        return [n for n, ok in (("Outlook", cfg.ms_refresh_token), ("Gmail", cfg.google_refresh_token),
                                ("Notion", cfg.notion_token)) if ok]

    # ---- the questions the assistant asks -------------------------------------
    def schedule(self, day: datetime) -> dict:
        tz = Config().timezone
        start = datetime.combine(day.date(), dtime.min, tz)
        events, problems = [], []
        if self.demo:
            from agent.demo import sample
            events = sample(datetime.now(tz))[0]
        else:
            for name in ("Outlook", "Gmail"):
                try:
                    events += self.use(name, lambda c: c.events(start, start + timedelta(days=1)))
                except Exception as e:
                    problems.append(f"{'Outlook' if name == 'Outlook' else 'Google'} calendar: {e}")
        events = calendar_math.localize(events, tz)
        now = datetime.now(tz)
        return {
            "date": day.strftime("%A %B %-d"),
            "events": [{"time": "all day" if e["all_day"] else f"{e['start_local'][11:16]}-{e['end_local'][11:16]}",
                        "title": e["title"], "calendar": e["source"], "organizer": e["organizer"],
                        "you_organize": e["you_organize"], "location": e["location"], "agenda": e["agenda"][:300],
                        "done": not e["all_day"] and e["end_local"] <= now.isoformat(timespec="minutes")}
                       for e in events],
            "conflicts": calendar_math.conflicts(events),
            "free_90min_blocks": calendar_math.focus_gaps(events, max(now, start), tz),
            "unavailable": problems,
        }

    def recent_mail(self, hours: int) -> dict:
        since = datetime.now(Config().timezone) - timedelta(hours=hours)
        mail, problems = [], []
        if self.demo:
            from agent.demo import sample
            mail = sample(datetime.now(Config().timezone))[2]
        else:
            for name in ("Outlook", "Gmail"):
                try:
                    mail += self.use(name, lambda c: c.inbox(since))
                except Exception as e:
                    problems.append(f"{name}: {e}")
        mail.sort(key=lambda m: m["received"], reverse=True)
        return {"emails": [{"id": m["id"], "from": m["from"], "subject": m["subject"], "received": m["received"],
                            "you_already_replied": m["you_replied_after"], "preview": m["body"][:400]} for m in mail],
                "unavailable": problems}

    def search_mail(self, query: str) -> dict:
        if self.demo:
            return {"emails": [], "unavailable": []}
        found, problems = [], []
        for name in ("Outlook", "Gmail"):
            try:
                found += self.use(name, lambda c: c.search(query))
            except Exception as e:
                problems.append(f"{name}: {e}")
        return {"emails": found, "unavailable": problems}

    def read_mail(self, email_id: str) -> dict:
        if self.demo:
            from agent.demo import sample
            m = next(x for x in sample(datetime.now(Config().timezone))[2] if x["id"] == email_id)
            return {k: m[k] for k in ("from", "to", "subject", "received", "body")}
        return self.use(_source(email_id), lambda c: c.read(email_id[2:]))

    def draft_reply(self, email_id: str, text: str) -> bool:
        if self.demo:
            return True
        return self.use(_source(email_id), lambda c: c.create_reply_draft(email_id[2:], text))

    def tasks(self) -> dict:
        if self.demo:
            from agent.demo import sample
            return {"tasks": sample(datetime.now(Config().timezone))[4]}
        tasks, notes = self.use("Notion", lambda c: c.tasks_and_notes())
        return {"tasks": tasks, "priority_pages": notes}

    def add_todo(self, text: str) -> None:
        if not self.demo:
            self.use("Notion", lambda c: c.add_todo(text))


def _source(email_id: str) -> str:
    if email_id.startswith("o:"):
        return "Outlook"
    if email_id.startswith("g:"):
        return "Gmail"
    raise ValueError("Unknown email id; use an id returned by list_emails or search_emails.")
