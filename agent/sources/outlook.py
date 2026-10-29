"""Microsoft 365: Outlook calendar + mail via Microsoft Graph (delegated, refresh-token auth)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.ReadWrite Calendars.Read"
BODY_CHARS = 6000


class Outlook:
    def __init__(self, client_id: str, tenant: str, refresh_token: str):
        r = requests.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={"client_id": client_id, "grant_type": "refresh_token",
                  "refresh_token": refresh_token, "scope": SCOPES},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Microsoft sign-in failed: {r.json().get('error_description', r.text)[:200]}")
        tok = r.json()
        # Microsoft rotates refresh tokens; main.py saves the new one so the workflow can store it.
        self.new_refresh_token = tok.get("refresh_token")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {tok['access_token']}",
            "Prefer": 'outlook.body-content-type="text"',
        })
        self.me = self._get(f"{GRAPH}/me", {"$select": "mail,userPrincipalName"})

    def _get(self, url: str, params: dict | None = None) -> dict:
        r = self.s.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def _all(self, url: str, params: dict, cap: int = 200) -> list[dict]:
        items, data = [], self._get(url, params)
        while True:
            items += data.get("value", [])
            nxt = data.get("@odata.nextLink")
            if not nxt or len(items) >= cap:
                return items[:cap]
            data = self._get(nxt)

    # ---- calendar -------------------------------------------------------
    def events(self, start: datetime, end: datetime) -> list[dict]:
        rows = self._all(f"{GRAPH}/me/calendarView", {
            "startDateTime": start.astimezone(timezone.utc).isoformat(),
            "endDateTime": end.astimezone(timezone.utc).isoformat(),
            "$select": "id,subject,start,end,isAllDay,isCancelled,isOrganizer,organizer,attendees,"
                       "hasAttachments,isOnlineMeeting,onlineMeeting,bodyPreview,showAs,location",
            "$orderby": "start/dateTime",
            "$top": "100",
        })
        out = []
        for e in rows:
            if e.get("isCancelled"):
                continue
            out.append({
                "id": "o:" + e["id"],
                "source": "Outlook",
                "title": e.get("subject") or "(no title)",
                "start": e["start"]["dateTime"][:10] if e.get("isAllDay") else _graph_dt(e["start"]),
                "end": e["end"]["dateTime"][:10] if e.get("isAllDay") else _graph_dt(e["end"]),
                "all_day": e.get("isAllDay", False),
                "free": e.get("showAs") == "free",
                "organizer": (e.get("organizer") or {}).get("emailAddress", {}).get("name", ""),
                "you_organize": e.get("isOrganizer", False),
                "attendees": len(e.get("attendees") or []),
                "has_doc_or_link": bool(e.get("hasAttachments") or e.get("isOnlineMeeting")),
                "location": (e.get("location") or {}).get("displayName", ""),
                "agenda": (e.get("bodyPreview") or "")[:500],
            })
        return out

    # ---- mail -----------------------------------------------------------
    def inbox(self, since: datetime) -> list[dict]:
        rows = self._all(f"{GRAPH}/me/mailFolders/inbox/messages", {
            "$filter": f"receivedDateTime ge {_z(since)}",
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                       "uniqueBody,bodyPreview,inferenceClassification,hasAttachments",
            "$top": "50",
        })
        # One "did I reply?" lookup per email; run them side by side instead of one at a time.
        with ThreadPoolExecutor(max_workers=8) as pool:
            replied = list(pool.map(lambda m: self._replied(m["conversationId"], m["receivedDateTime"]), rows))
        out = []
        for m, you_replied in zip(rows, replied):
            body = ((m.get("uniqueBody") or {}).get("content") or m.get("bodyPreview") or "").strip()
            out.append({
                "id": "o:" + m["id"],
                "source": "Outlook",
                "from": _addr(m.get("from")),
                "to": ", ".join(_addr(x) for x in m.get("toRecipients") or []),
                "cc": ", ".join(_addr(x) for x in m.get("ccRecipients") or []),
                "subject": m.get("subject") or "",
                "received": m["receivedDateTime"],
                "you_replied_after": you_replied,
                "category_hint": "focused" if m.get("inferenceClassification") == "focused" else "other",
                "has_attachments": m.get("hasAttachments", False),
                "body": _clip(body),
            })
        return out

    def _replied(self, conversation_id: str, after_iso: str) -> bool | None:
        try:
            hits = self._get(f"{GRAPH}/me/mailFolders/sentitems/messages", {
                "$filter": f"conversationId eq '{conversation_id}' and sentDateTime ge {after_iso}",
                "$select": "id", "$top": "1"})
            return bool(hits.get("value"))
        except requests.HTTPError:
            return None  # unknown; the model is told to treat None as "couldn't check"

    def unanswered_sent(self, now: datetime) -> list[dict]:
        """Emails you sent 1-7 days ago that nobody has replied to yet."""
        rows = self._all(f"{GRAPH}/me/mailFolders/sentitems/messages", {
            "$filter": f"sentDateTime ge {_z(now - timedelta(days=7))} and sentDateTime le {_z(now - timedelta(days=1))}",
            "$orderby": "sentDateTime desc",
            "$select": "id,conversationId,subject,toRecipients,sentDateTime,bodyPreview",
            "$top": "15"}, cap=15)
        out = []
        for m in rows:
            try:
                replies = self._get(f"{GRAPH}/me/messages", {
                    "$filter": f"conversationId eq '{m['conversationId']}' and receivedDateTime gt {m['sentDateTime']}",
                    "$select": "id", "$top": "1"}).get("value")
            except requests.HTTPError:
                continue
            if not replies:
                out.append({"source": "Outlook", "to": ", ".join(_addr(x) for x in m.get("toRecipients") or []),
                            "subject": m.get("subject") or "", "sent": m["sentDateTime"],
                            "preview": (m.get("bodyPreview") or "")[:300]})
        return out

    def create_reply_draft(self, message_id: str, text: str) -> None:
        r = self.s.post(f"{GRAPH}/me/messages/{message_id}/createReply", json={"comment": text}, timeout=60)
        r.raise_for_status()


def _graph_dt(d: dict) -> str:
    # calendarView returns UTC wall time without offset unless a Prefer timezone is sent.
    return datetime.fromisoformat(d["dateTime"][:19]).replace(tzinfo=timezone.utc).isoformat()


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _addr(x: dict | None) -> str:
    e = (x or {}).get("emailAddress", {})
    return f"{e.get('name', '')} <{e.get('address', '')}>".strip()


def _clip(s: str) -> str:
    return s if len(s) <= BODY_CHARS else s[:BODY_CHARS] + " …[truncated]"
