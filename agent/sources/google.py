"""Google: Calendar + Gmail via the official API client (refresh-token auth)."""
import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
BODY_CHARS = 6000


class Google:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        creds = Credentials(None, refresh_token=refresh_token, client_id=client_id,
                            client_secret=client_secret, token_uri="https://oauth2.googleapis.com/token",
                            scopes=SCOPES)
        self.cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.gm = build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ---- calendar -------------------------------------------------------
    def calendars(self) -> list[dict]:
        """The calendars shown in Satty's Google Calendar (ticked in the sidebar), primary first."""
        items, token = [], None
        while True:
            res = self.cal.calendarList().list(pageToken=token, minAccessRole="reader").execute()
            items += res.get("items", [])
            token = res.get("nextPageToken")
            if not token:
                break
        shown = [c for c in items if c.get("selected") or c.get("primary")]
        return sorted(shown, key=lambda c: not c.get("primary"))

    def events(self, start: datetime, end: datetime) -> list[dict]:
        rows = []
        for cal in self.calendars():
            res = self.cal.events().list(
                calendarId=cal["id"], timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=100).execute()
            rows += [(cal, e) for e in res.get("items", [])]
        out, seen = [], set()
        for cal, e in rows:
            # The same meeting can sit on several calendars; keep it once.
            key = e.get("iCalUID") or e["id"]
            if e.get("status") == "cancelled" or key in seen:
                continue
            seen.add(key)
            all_day = "date" in e["start"]
            out.append({
                "id": "g:" + e["id"],
                "source": "Google",
                "calendar": cal.get("summaryOverride") or cal.get("summary", ""),
                "title": e.get("summary") or "(no title)",
                "start": e["start"].get("dateTime") or e["start"]["date"],
                "end": e["end"].get("dateTime") or e["end"]["date"],
                "all_day": all_day,
                "free": e.get("transparency") == "transparent",
                "organizer": (e.get("organizer") or {}).get("displayName") or (e.get("organizer") or {}).get("email", ""),
                "you_organize": bool((e.get("organizer") or {}).get("self")),
                "attendees": len(e.get("attendees") or []),
                "has_doc_or_link": bool(e.get("attachments") or e.get("hangoutLink") or e.get("conferenceData")),
                "location": e.get("location", ""),
                "agenda": (e.get("description") or "")[:500],
            })
        return out

    # ---- mail -----------------------------------------------------------
    def inbox(self, since: datetime) -> list[dict]:
        hours = max(1, int((datetime.now(timezone.utc) - since).total_seconds() // 3600))
        q = f"in:inbox newer_than:{hours}h -category:promotions -category:social -in:spam"
        ids = self._list_ids(q, cap=100)
        out = []
        for mid in ids:
            m = self.gm.users().messages().get(userId="me", id=mid, format="full").execute()
            h = _headers(m)
            out.append({
                "id": "g:" + mid,
                "source": "Gmail",
                "from": h.get("from", ""),
                "to": h.get("to", ""),
                "cc": h.get("cc", ""),
                "subject": h.get("subject", ""),
                "received": datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc).isoformat(),
                "you_replied_after": self._replied(m),
                "category_hint": "updates" if "CATEGORY_UPDATES" in m.get("labelIds", []) else "primary",
                "has_attachments": any(p.get("filename") for p in _parts(m["payload"])),
                "body": _clip(_plain_text(m["payload"]) or m.get("snippet", "")),
            })
        return out

    def _list_ids(self, q: str, cap: int) -> list[str]:
        ids, token = [], None
        while len(ids) < cap:
            res = self.gm.users().messages().list(userId="me", q=q, pageToken=token, maxResults=50).execute()
            ids += [x["id"] for x in res.get("messages", [])]
            token = res.get("nextPageToken")
            if not token:
                break
        return ids[:cap]

    def _replied(self, m: dict) -> bool:
        t = self.gm.users().threads().get(userId="me", id=m["threadId"], format="minimal").execute()
        return any("SENT" in x.get("labelIds", []) and int(x["internalDate"]) > int(m["internalDate"])
                   for x in t.get("messages", []))

    def unanswered_sent(self, now: datetime) -> list[dict]:
        out = []
        for mid in self._list_ids("in:sent newer_than:7d older_than:1d", cap=15):
            m = self.gm.users().messages().get(userId="me", id=mid, format="metadata",
                                               metadataHeaders=["To", "Subject"]).execute()
            t = self.gm.users().threads().get(userId="me", id=m["threadId"], format="minimal").execute()
            later = [x for x in t["messages"] if int(x["internalDate"]) > int(m["internalDate"])]
            if not any("SENT" not in x.get("labelIds", []) for x in later):
                h = _headers(m)
                out.append({"source": "Gmail", "to": h.get("to", ""), "subject": h.get("subject", ""),
                            "sent": datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc).isoformat(),
                            "preview": m.get("snippet", "")[:300]})
        return out

    def search(self, query: str, limit: int = 10) -> list[dict]:
        out = []
        for mid in self._list_ids(query, cap=limit):
            m = self.gm.users().messages().get(userId="me", id=mid, format="metadata",
                                               metadataHeaders=["From", "Subject"]).execute()
            h = _headers(m)
            out.append({"id": "g:" + mid, "source": "Gmail", "from": h.get("from", ""), "subject": h.get("subject", ""),
                        "received": datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc).isoformat(),
                        "preview": m.get("snippet", "")[:300]})
        return out

    def read(self, message_id: str) -> dict:
        m = self.gm.users().messages().get(userId="me", id=message_id, format="full").execute()
        h = _headers(m)
        return {"from": h.get("from", ""), "to": h.get("to", ""), "cc": h.get("cc", ""), "subject": h.get("subject", ""),
                "received": datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc).isoformat(),
                "body": _clip(_plain_text(m["payload"]) or m.get("snippet", ""))}

    def create_reply_draft(self, message_id: str, text: str) -> bool:
        """Saves a reply draft in the thread. Returns False if that thread already has a draft."""
        m = self.gm.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"]).execute()
        thread = self.gm.users().threads().get(userId="me", id=m["threadId"], format="minimal").execute()
        if any("DRAFT" in x.get("labelIds", []) for x in thread.get("messages", [])):
            return False
        h = _headers(m)
        msg = EmailMessage()
        msg["To"] = h.get("reply-to") or h.get("from", "")
        subject = h.get("subject", "")
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if h.get("message-id"):
            msg["In-Reply-To"] = h["message-id"]
            msg["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
        msg.set_content(text)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self.gm.users().drafts().create(
            userId="me", body={"message": {"raw": raw, "threadId": m["threadId"]}}).execute()
        return True


def _headers(m: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}


def _parts(p: dict):
    yield p
    for c in p.get("parts", []) or []:
        yield from _parts(c)


def _plain_text(payload: dict) -> str:
    for p in _parts(payload):
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "replace").strip()
    return ""


def _clip(s: str) -> str:
    return s if len(s) <= BODY_CHARS else s[:BODY_CHARS] + " …[truncated]"
