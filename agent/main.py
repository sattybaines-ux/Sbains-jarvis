"""Jarvis morning brief: gather -> think -> draft -> brief -> voice -> publish -> push.

Run:  python -m agent.main            (real run; needs the secrets in README)
      python -m agent.main --demo     (sample data, no API calls; for testing the iPhone app)
"""
import base64
import copy
import json
import sys
import time as clock
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from . import calendar_math
from .config import ROOT, Config
from .ledger import Ledger
from .publish import write_site


def plain_error(e: Exception) -> str:
    return (str(e) or type(e).__name__).splitlines()[0][:200]


@dataclass
class Snapshot:
    """Everything read from the accounts at one moment (the server keeps one warm for quick refreshes)."""
    taken: datetime
    led: Ledger
    clients: dict
    events: list
    tomorrow: list
    emails: list
    followups: list
    tasks: list
    notes: list


def collect(cfg: Config, demo: bool = False, quick: bool = False) -> Snapshot:
    tz = cfg.timezone
    now = datetime.now(tz)
    day_start = datetime.combine(now.date(), time.min, tz)
    tomorrow_noon = day_start + timedelta(days=1, hours=12)
    led = Ledger()
    for key, label in [("outlook_cal", "Outlook Calendar"), ("google_cal", "Google Calendar"),
                       ("outlook_mail", "Outlook Mail"), ("gmail", "Gmail"), ("notion", "Notion"),
                       ("notion_page", "Notion brief page"), ("voice", "Fish Audio")]:
        led.add(key, label)

    events, tomorrow, emails, followups, tasks, notes = [], [], [], [], [], []
    clients = {}

    if demo:
        from .demo import sample
        events, tomorrow, emails, followups, tasks, notes = sample(now)
        for k in ("outlook_cal", "google_cal", "outlook_mail", "gmail", "notion"):
            led.set(k, "online", "Demo data.")
    else:
        # The three accounts are fetched at the same time; each one only touches its own ledger rows.
        def microsoft():
            try:
                from .sources.outlook import connect
                ms = clients["Outlook"] = connect(cfg)
                gather(led, "outlook_cal", lambda: ms.events(day_start, tomorrow_noon), events, "events")
                n = gather(led, "outlook_mail", lambda: ms.inbox(now - timedelta(hours=24)), emails, "emails in 24h")
                if n is not None and not quick:
                    try:
                        followups.extend(ms.unanswered_sent(now))
                    except Exception as e:
                        print("outlook follow-ups skipped:", plain_error(e))
            except Exception as e:
                for k in ("outlook_cal", "outlook_mail"):
                    led.set(k, "offline", plain_error(e))

        def google():
            if not cfg.google_refresh_token:
                for k in ("google_cal", "gmail"):
                    led.set(k, "offline", "Not connected (no GOOGLE_REFRESH_TOKEN).")
                return
            try:
                from .sources.google import Google
                g = clients["Gmail"] = Google(cfg.google_client_id, cfg.google_client_secret, cfg.google_refresh_token)
                gather(led, "google_cal", lambda: g.events(day_start, tomorrow_noon), events, "events")
                n = gather(led, "gmail", lambda: g.inbox(now - timedelta(hours=24)), emails, "emails in 24h")
                if n is not None and not quick:
                    try:
                        followups.extend(g.unanswered_sent(now))
                    except Exception as e:
                        print("gmail follow-ups skipped:", plain_error(e))
            except Exception as e:
                for k in ("google_cal", "gmail"):
                    led.set(k, "offline", plain_error(e))

        def notion():
            if not cfg.notion_token:
                led.set("notion", "offline", "Not connected (no NOTION_TOKEN).")
                return
            try:
                from .sources.notion import Notion
                n = clients["Notion"] = Notion(cfg.notion_token)
                t, pages = n.tasks_and_notes()
                tasks.extend(t)
                notes.extend(pages)
                led.set("notion", "online" if t or pages else "empty",
                        f"{len(t)} open tasks, {len(pages)} priority pages read.")
            except Exception as e:
                led.set("notion", "offline", plain_error(e))

        with ThreadPoolExecutor(max_workers=3) as pool:
            for f in [pool.submit(fn) for fn in (microsoft, google, notion)]:
                f.result()
    return Snapshot(now, led, clients, events, tomorrow, emails, followups, tasks, notes)


def run(cfg: Config, demo: bool = False, publish: bool = True, quick: bool = False,
        snapshot: "Snapshot | None" = None, quick_writer=None) -> dict:
    """publish: write the encrypted GitHub Pages site. quick: the fast refresh used by the Jarvis server
    (one Claude call, no follow-up scan, no voice or Notion archive page)."""
    started = clock.monotonic()

    timings = {}

    def timer(phase: str) -> None:  # timings only; logs are public
        timings[phase] = round(clock.monotonic() - started, 1)
        print(f"[{timings[phase]:5.1f}s] {phase}")

    tz = cfg.timezone
    now = datetime.now(tz)
    day_start = datetime.combine(now.date(), time.min, tz)
    day_end = day_start + timedelta(days=1)
    tomorrow_noon = day_end + timedelta(hours=12)
    today_label = now.strftime("%A %B %-d, %Y")

    snap = snapshot or collect(cfg, demo, quick)
    led = copy.deepcopy(snap.led)
    clients = snap.clients
    events, tomorrow, emails = copy.deepcopy(snap.events), copy.deepcopy(snap.tomorrow), copy.deepcopy(snap.emails)
    followups, tasks, notes = list(snap.followups), list(snap.tasks), list(snap.notes)
    timer("gather accounts")

    # ---- calendar math (deterministic) ---------------------------------------
    events = calendar_math.localize(events, tz)
    for e in events:
        e["past"] = not e["all_day"] and e["end_local"] <= now.isoformat(timespec="minutes")
    today_iso = now.date().isoformat()
    tomorrow = [e for e in events if e["start_local"][:10] > today_iso]
    events = [e for e in events if e["start_local"][:10] <= today_iso and e["end_local"][:10] >= today_iso]
    conflicts = calendar_math.conflicts(events)
    gaps = calendar_math.focus_gaps(events, now, tz)
    cal_online = led.online("outlook_cal") or led.online("google_cal")
    mail_online = led.online("outlook_mail") or led.online("gmail")

    data = {
        "today": today_label,
        "now_local": now.isoformat(timespec="minutes"),
        "time_of_day": part_of_day(now),
        "source_status": led.as_dict(),
        "calendar_today": events,
        "calendar_tomorrow_morning": tomorrow,
        "conflicts": conflicts,
        "focus_gaps_90min": gaps,
        # A quick refresh only needs the gist of each email, which keeps Claude fast.
        "emails_last_24h": [{**m, "body": m["body"][:500]} for m in emails] if quick else emails,
        "sent_emails_with_no_reply_yet": followups,
        "notion_open_tasks": tasks,
        "notion_priority_pages": notes,
    }

    # ---- Claude: triage ------------------------------------------------------
    quick_lines = None
    if demo:
        from .demo import fake_triage
        tri = fake_triage(events, emails)
    else:
        from .brain import Brain
        brain = Brain(cfg.model, cfg.user_name, cfg.profile, quick_writer)
        if quick:
            tri, quick_lines = brain.quick(today_label, data)
        else:
            tri = brain.triage(today_label, data)
    timer("Claude: triage")

    by_id = {e["id"]: e for e in emails}
    groups = {"needs_reply": 0, "fyi": 0, "ignore": 0}
    drafts, suspicious = [], []
    for call in tri.emails:
        mail = by_id.get(call.id)
        if not mail:
            continue  # model referenced something we didn't give it; ignore
        group = "fyi" if call.group == "needs_reply" and mail["you_replied_after"] else call.group
        groups[group] += 1
        if call.suspicious_note:
            suspicious.append(f"{mail['from']}: {call.suspicious_note}")
        if group != "needs_reply":
            continue
        label = f"{mail['from']} — {mail['subject']}"
        if quick:  # no drafting on a quick refresh; the morning brief or "draft a reply to…" does that
            drafts.append({"label": label, "source": mail["source"], "created": False, "needsReply": True})
            continue
        if call.handle_yourself or not call.draft_reply:
            drafts.append({"label": label + " (handle yourself)", "source": mail["source"], "created": False})
            continue
        ok, new = True, True
        if not demo:
            try:
                # False = a draft from an earlier run is already waiting in that thread; don't add another.
                new = clients[mail["source"]].create_reply_draft(call.id[2:], call.draft_reply)
            except Exception as e:
                ok = False
                print(f"A {mail['source']} draft failed: {type(e).__name__}")
        drafts.append({"label": label, "source": mail["source"], "created": ok, "text": call.draft_reply,
                       "alreadyWaiting": ok and not new})

    prep_ids = set(tri.needs_prep_event_ids)
    timer("save drafts")
    numbers = {
        "meetingsToday": len([e for e in events if not e["all_day"]]) if cal_online else None,
        "needsPrep": len([e for e in events if e["id"] in prep_ids]) if cal_online else None,
        "conflicts": len(conflicts) if cal_online else None,
        "focusGaps": len(gaps) if cal_online else None,
        "emailsScanned": len(emails) if mail_online else None,
        "needsReply": groups["needs_reply"] if mail_online else None,
        "draftsCreated": sum(d["created"] for d in drafts) if mail_online else None,
        "fyi": groups["fyi"] if mail_online and not quick else None,  # a quick refresh only finds what needs you
        "ignored": groups["ignore"] if mail_online and not quick else None,
        "tasksOpen": len(tasks) if led.online("notion") else None,
        "tasksDueToday": len([t for t in tasks if (t["due"] or "")[:10] == now.date().isoformat()])
        if led.online("notion") else None,
    }

    facts = {
        "today": today_label,
        "source_status": {k: v["status"] + " - " + v["log"] for k, v in led.as_dict().items()
                          if k not in ("notion_page", "voice")},
        "numbers": numbers,
        "needs_prep": [f"{e['start_local'][11:16]} {e['title']}" for e in events if e["id"] in prep_ids],
        "conflicts": conflicts,
        "focus_gaps": gaps,
        "drafts_waiting": [d["label"] for d in drafts if d["created"]],
        "handle_yourself": [d["label"] for d in drafts if not d["created"]],
        "suspicious": suspicious,
        "top3": [t.model_dump() for t in tri.top3],
        "one_thing": tri.one_thing,
    }

    # ---- Claude: spoken brief ------------------------------------------------
    if demo:
        from .demo import fake_brief
        lines = fake_brief(facts)
    elif quick_lines:
        lines = quick_lines
    else:
        lines = brain.brief(facts)
    timer("Claude: spoken brief")
    brief_text = "\n".join(lines)

    # ---- voice ---------------------------------------------------------------
    audio = None
    if cfg.fish_api_key and not demo and not quick:
        try:
            from .voice import speak
            audio = speak(" ".join(lines), cfg.fish_api_key, cfg.fish_voice_id)
            led.set("voice", "online", f"{len(audio) // 1024} KB of audio.")
        except Exception as e:
            led.set("voice", "offline", plain_error(e))
    else:
        led.set("voice", "offline", "Skipped on quick refresh." if quick else
                "Not connected (no FISH_AUDIO_API_KEY)." if not demo else "Demo: no audio.")

    timer("voice")

    # ---- Notion brief page ---------------------------------------------------
    if quick:
        led.set("notion_page", "empty", "Skipped on quick refresh.")
    elif "Notion" in clients:
        try:
            clients["Notion"].save_brief(f"Morning Brief — {now.date()}", lines,
                                         [d["label"] for d in drafts], led.footer())
            led.set("notion_page", "online", f"Saved Morning Brief — {now.date()}.")
        except Exception as e:
            led.set("notion_page", "offline", plain_error(e))
    else:
        led.set("notion_page", "offline", "Notion not connected.")

    timer("Notion brief page")

    # ---- publish + push ------------------------------------------------------
    payload = {
        "generatedAt": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "dateLabel": today_label,
        "brief": lines,
        "numbers": numbers,
        "top3": facts["top3"],
        "oneThing": tri.one_thing,
        "schedule": [{"time": "All day" if e["all_day"] else e["start_local"][11:16] + "–" + e["end_local"][11:16],
                      "start": e["start_local"], "end": e["end_local"], "past": e["past"],
                      "title": e["title"], "source": e["source"], "needsPrep": e["id"] in prep_ids}
                     for e in events],
        "quick": quick,
        "conflicts": [" vs ".join(p) for p in conflicts],
        "focusGaps": gaps,
        "drafts": drafts,
        "suspicious": suspicious,
        "audio": base64.b64encode(audio).decode() if audio else None,
    }

    payload["connectors"] = led.as_dict()  # final statuses, including voice
    payload["timings"] = timings
    if not publish:
        print(led.footer())
        return payload

    # The push itself is sent by agent.notify after the site is deployed.
    cfg.out_dir.mkdir(exist_ok=True)
    (cfg.out_dir / "push.json").write_text(json.dumps({"title": "Morning brief ready", "body": lines[0]}))
    if not cfg.passphrase:
        raise SystemExit("BRIEF_PASSPHRASE is required so the published brief is encrypted.")
    write_site(cfg.site_dir, ROOT / "app", payload, cfg.passphrase, cfg.vapid_public_key)

    cfg.out_dir.mkdir(exist_ok=True)
    (cfg.out_dir / "brief.txt").write_text(brief_text + "\n\n" + led.footer() + "\n")
    # Logs on a public repo are public: print statuses and counts only, never content.
    print(led.footer())
    print(f"{len(lines)} brief lines, {sum(d['created'] for d in drafts)} drafts created.")
    return payload


def part_of_day(now: datetime) -> str:
    return "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"


def gather(led: Ledger, key: str, fn, sink: list, noun: str) -> int | None:
    try:
        rows = fn()
    except Exception as e:
        print(f"{key} failed: {type(e).__name__}")
        led.set(key, "offline", plain_error(e))
        return None
    sink += rows
    led.set(key, "online" if rows else "empty", f"{len(rows)} {noun}." if rows else f"No {noun}.")
    return len(rows)


if __name__ == "__main__":
    run(Config(), demo="--demo" in sys.argv)
