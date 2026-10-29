"""Sample data for `python -m agent.main --demo` - exercises the whole pipeline with no API calls."""
from datetime import datetime, time, timedelta

from .brain import FINAL_LINE, EmailCall, TopItem, Triage


def sample(now: datetime):
    tz = now.tzinfo
    at = lambda h, m=0: datetime.combine(now.date(), time(h, m), tz).isoformat()
    ev = lambda i, src, title, s, e, org=False: {
        "id": i, "source": src, "title": title, "start": s, "end": e, "all_day": False, "free": False,
        "organizer": "Satty" if org else "Dana", "you_organize": org, "attendees": 4,
        "has_doc_or_link": True, "location": "", "agenda": ""}
    events = [
        ev("o:1", "Outlook", "B2W Inform replacement – vendor demo", at(9), at(10), org=True),
        ev("o:2", "Outlook", "Site safety huddle", at(10, 30), at(11)),
        ev("g:3", "Google", "Dentist", at(10, 45), at(11, 30)),
    ]
    mail = lambda i, src, frm, subj, body, replied=False: {
        "id": i, "source": src, "from": frm, "to": "Satty", "cc": "", "subject": subj,
        "received": now.isoformat(), "you_replied_after": replied, "category_hint": "focused",
        "has_attachments": False, "body": body}
    emails = [
        mail("o:a", "Outlook", "Mike R <mike@rotomill.ca>", "RD rollout date?", "Can we lock the RD rollout for next week?"),
        mail("o:b", "Outlook", "B2W Support", "Ticket #4412 updated", "Your ticket has been updated."),
        mail("g:c", "Gmail", "News <news@example.com>", "Weekly digest", "Top stories..."),
    ]
    followups = [{"source": "Outlook", "to": "Priya <priya@rotomill.ca>", "subject": "Equipment hours export",
                  "sent": (now - timedelta(days=3)).isoformat(), "preview": "Could you send the export?"}]
    tasks = [{"title": "Draft Inform replacement scorecard", "due": now.date().isoformat(), "status": "In progress",
              "project": "Tasks"}]
    return events, [], emails, followups, tasks, []


def fake_triage(events, emails) -> Triage:
    return Triage(
        needs_prep_event_ids=["o:1"],
        emails=[EmailCall(id="o:a", group="needs_reply", draft_reply="Hi Mike, [confirm date?] works for me. Satty"),
                EmailCall(id="o:b", group="fyi"), EmailCall(id="g:c", group="ignore")],
        top3=[TopItem(rank=1, item="Prep the Inform vendor demo", why="You're running it at 9."),
              TopItem(rank=2, item="Answer Mike on the RD rollout", why="He's blocked on your date."),
              TopItem(rank=3, item="Finish the Inform scorecard", why="Due today in Notion.")],
        one_thing="Priya hasn't answered your equipment-hours request from three days ago.")


def fake_brief(facts) -> list[str]:
    return [f"Morning, Satty. {facts['today']}: three meetings, all before noon.",
            "The Inform demo at nine needs prep, and the safety huddle overlaps your dentist at ten forty-five.",
            "Three emails: one needs a reply, one FYI, one ignored; one draft is waiting for you.",
            "First, prep the Inform vendor demo, since you're running it at nine.",
            "Second, answer Mike on the RD rollout; he's blocked on your date.",
            "Third, finish the Inform scorecard; it's due today.",
            "Heads up: Priya still hasn't sent the equipment-hours export you asked for.",
            FINAL_LINE]
