"""Notion: read tasks/priorities, and save each brief as a page under "Morning Briefs"."""
import requests

API = "https://api.notion.com/v1"
SEARCH_TERMS = ["tasks", "to do", "priorities", "B2W", "Roto Dentist"]
DONE_WORDS = {"done", "complete", "completed", "archived", "cancelled", "canceled", "closed"}


class Notion:
    def __init__(self, token: str):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"})

    def _post(self, path: str, body: dict) -> dict:
        r = self.s.post(f"{API}{path}", json=body, timeout=60)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> dict:
        r = self.s.get(f"{API}{path}", timeout=60)
        r.raise_for_status()
        return r.json()

    def tasks_and_notes(self) -> tuple[list[dict], list[dict]]:
        """Returns (tasks from any matching databases, text of matching plain pages)."""
        seen, dbs, pages = set(), [], []
        for term in SEARCH_TERMS:
            for hit in self._post("/search", {"query": term, "page_size": 20}).get("results", []):
                if hit["id"] in seen:
                    continue
                seen.add(hit["id"])
                if hit["object"] == "database":
                    dbs.append(hit)
                elif hit["object"] == "page" and hit.get("parent", {}).get("type") != "database_id":
                    pages.append(hit)

        tasks = []
        for db in dbs[:5]:
            for row in self._post(f"/databases/{db['id']}/query", {"page_size": 100}).get("results", []):
                t = _task(row, _plain(db.get("title", [])))
                if t:
                    tasks.append(t)

        notes = []
        for p in pages[:5]:
            title = _title(p)
            if title.startswith("Morning Brief"):
                continue
            blocks = self._get(f"/blocks/{p['id']}/children?page_size=100").get("results", [])
            text = "\n".join(_block_text(b) for b in blocks).strip()
            if text:
                notes.append({"title": title, "text": text[:4000]})
        return tasks, notes

    def add_todo(self, text: str, page_title: str = "To Do List") -> None:
        """Appends an unchecked to-do to the page with this title (it must be shared with the connection)."""
        for hit in self._post("/search", {"query": page_title,
                                          "filter": {"property": "object", "value": "page"}}).get("results", []):
            if _title(hit).strip().lower() == page_title.lower():
                r = self.s.patch(f"{API}/blocks/{hit['id']}/children", timeout=60, json={"children": [{
                    "object": "block", "type": "to_do",
                    "to_do": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}], "checked": False}}]})
                r.raise_for_status()
                return
        raise RuntimeError(f'No page named "{page_title}" is shared with the Jarvis connection.')

    def save_brief(self, title: str, lines: list[str], drafts: list[str], footer: str) -> str:
        parent = None
        for hit in self._post("/search", {"query": "Morning Briefs",
                                          "filter": {"property": "object", "value": "page"}}).get("results", []):
            if _title(hit) == "Morning Briefs":
                parent = hit["id"]
                break
        if not parent:
            raise RuntimeError('No page named "Morning Briefs" is shared with the integration.')
        para = lambda t: {"object": "block", "type": "paragraph",
                          "paragraph": {"rich_text": [{"type": "text", "text": {"content": t[:1900]}}]}}
        children = [para(l) for l in lines]
        children.append({"object": "block", "type": "heading_3",
                         "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Drafts waiting"}}]}})
        children += [{"object": "block", "type": "bulleted_list_item",
                      "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": d[:1900]}}]}}
                     for d in drafts] or [para("None.")]
        children.append(para(footer))
        page = self._post("/pages", {"parent": {"page_id": parent},
                                     "properties": {"title": {"title": [{"text": {"content": title}}]}},
                                     "children": children})
        return page.get("url", "")


def _plain(rich: list) -> str:
    return "".join(x.get("plain_text", "") for x in rich or [])


def _title(obj: dict) -> str:
    for prop in obj.get("properties", {}).values():
        if prop.get("type") == "title":
            return _plain(prop["title"])
    return ""


def _block_text(b: dict) -> str:
    body = b.get(b["type"], {})
    text = _plain(body.get("rich_text", []))
    if b["type"] == "to_do":
        return f"[{'x' if body.get('checked') else ' '}] {text}"
    return text


def _task(row: dict, db_name: str) -> dict | None:
    title, due, status, done = "", None, "", False
    for name, prop in row.get("properties", {}).items():
        kind = prop.get("type")
        if kind == "title":
            title = _plain(prop["title"])
        elif kind == "date" and prop.get("date") and not due:
            due = prop["date"].get("start")
        elif kind in ("status", "select") and prop.get(kind):
            value = prop[kind].get("name", "")
            if not status or "status" in name.lower():
                status = value
            done = done or value.lower() in DONE_WORDS
        elif kind == "checkbox" and name.lower() in DONE_WORDS | {"done?", "complete?"}:
            done = done or prop["checkbox"]
    if not title or done:
        return None
    return {"title": title, "due": due, "status": status, "project": db_name}
