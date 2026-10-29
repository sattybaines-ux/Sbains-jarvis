"""Jarvis server: the iPhone app, the talking assistant, quick refresh, and the scheduled morning brief.

Run:  uvicorn server.app:app --host 127.0.0.1 --port 8000
      JARVIS_DEMO=1 uvicorn server.app:app ...   (sample data, for trying the app without accounts)
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.config import ROOT, Config
from agent.main import run as run_brief
from . import speech, store
from .accounts import Accounts
from .assistant import Assistant

DEMO = os.environ.get("JARVIS_DEMO") == "1"
COOKIE = "jarvis_session"
SESSION_DAYS = 180


def _secret() -> bytes:
    f = ROOT / "out" / "app_secret"
    if not f.exists():
        f.parent.mkdir(exist_ok=True)
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip().encode()


def _sign(expires: int) -> str:
    return f"{expires}.{hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()}"


def _valid(token: str | None) -> bool:
    try:
        expires, sig = (token or "").split(".", 1)
        return int(expires) > time.time() and hmac.compare_digest(sig, _sign(int(expires)).split(".", 1)[1])
    except ValueError:
        return False


accounts = Accounts(demo=DEMO)
assistant = Assistant(accounts, store.latest_brief)
_refreshing = asyncio.Lock()
_failed_logins: list[float] = []


# ---- morning brief schedule -----------------------------------------------------
def _next_brief(now: datetime) -> datetime:
    hh, mm = (int(x) for x in os.environ.get("BRIEF_TIME", "06:45").split(":"))
    days = {int(d) for d in os.environ.get("BRIEF_WEEKDAYS", "0,1,2,3,4").split(",")}  # Monday = 0
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    while t <= now or t.weekday() not in days:
        t = (t + timedelta(days=1)).replace(hour=hh, minute=mm)
    return t


async def _morning_loop():
    while True:
        now = datetime.now(Config().timezone)
        await asyncio.sleep((_next_brief(now) - now).total_seconds())
        try:
            await make_brief(quick=False)
            await notify("Morning brief ready", (store.latest_brief() or {}).get("brief", [""])[0])
        except Exception as e:
            print("Morning brief failed:", type(e).__name__, str(e)[:200])


async def make_brief(quick: bool) -> dict:
    async with _refreshing:
        payload = await asyncio.to_thread(run_brief, Config(), DEMO, False, quick)
        store.save_brief(payload)
        return payload


async def notify(title: str, body: str) -> None:
    cfg, subs = Config(), store.subscriptions()
    if not (cfg.vapid_private_key and subs):
        return
    from agent.publish import push
    try:
        await asyncio.to_thread(push, json.dumps(subs), cfg.vapid_private_key, cfg.vapid_subject, title, body)
    except Exception as e:
        print("Push failed:", e)


@asynccontextmanager
async def lifespan(_app):
    tasks = [asyncio.create_task(_morning_loop()), asyncio.create_task(asyncio.to_thread(speech.warm_up))]
    yield
    for t in tasks:
        t.cancel()
    await assistant.reset()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in ("/api/login", "/api/health") and not _valid(request.cookies.get(COOKIE)):
        return Response(status_code=401)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "no-cache"
    return response


# ---- auth ------------------------------------------------------------------------
class Login(BaseModel):
    passphrase: str


@app.post("/api/login")
async def login(body: Login, response: Response):
    recent = [t for t in _failed_logins if t > time.time() - 900]
    if len(recent) >= 10:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    expected = Config().passphrase
    if not expected or not hmac.compare_digest(body.passphrase.strip(), expected):
        _failed_logins.append(time.time())
        await asyncio.sleep(1)
        raise HTTPException(401, "That passphrase didn't work.")
    expires = int(time.time()) + SESSION_DAYS * 86400
    response.set_cookie(COOKIE, _sign(expires), max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=not DEMO, samesite="strict")
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/me")
async def me():
    cfg = Config()
    return {"name": cfg.user_name, "connected": accounts.connected() if not DEMO else ["Outlook", "Gmail", "Notion"],
            "voice": bool(cfg.fish_api_key), "vapidPublicKey": cfg.vapid_public_key, "demo": DEMO}


# ---- brief -----------------------------------------------------------------------
@app.get("/api/brief")
async def brief():
    b = store.latest_brief()
    if not b:
        raise HTTPException(404, "No brief yet.")
    return b


@app.post("/api/refresh")
async def refresh():
    try:
        return await make_brief(quick=True)
    except Exception as e:
        print("Refresh failed:", type(e).__name__, str(e)[:300])
        raise HTTPException(500, str(e).splitlines()[0][:160] if str(e) else type(e).__name__)


# ---- conversation ----------------------------------------------------------------
class Chat(BaseModel):
    message: str
    voice: bool = False


@app.post("/api/chat")
async def chat(body: Chat):
    async def stream():
        try:
            async for event in assistant.chat(body.message[:4000], body.voice):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            print("Chat failed:", type(e).__name__, str(e)[:300])
            await assistant.reset()
            yield f"data: {json.dumps({'type': 'error', 'message': 'I lost my train of thought. Try that again?'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/api/chat/reset")
async def chat_reset():
    await assistant.reset()
    return {"ok": True}


class Decision(BaseModel):
    id: str
    approve: bool


@app.post("/api/confirm")
async def confirm(body: Decision):
    try:
        return {"message": await assistant.confirm(body.id, body.approve)}
    except Exception as e:
        return {"message": f"That didn't work: {str(e).splitlines()[0][:200]}"}


# ---- voice -----------------------------------------------------------------------
@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Recording too long.")
    try:
        return {"text": await asyncio.to_thread(speech.transcribe, data)}
    except Exception as e:
        print("Transcribe failed:", e)
        raise HTTPException(503, "Voice input isn't available right now.")


class Speak(BaseModel):
    text: str


@app.post("/api/speak")
async def speak(body: Speak):
    try:
        audio = await asyncio.to_thread(speech.speak, body.text[:3000])
    except Exception as e:
        print("Speak failed:", e)
        audio = None
    return Response(audio, media_type="audio/mpeg") if audio else Response(status_code=204)


# ---- push ------------------------------------------------------------------------
@app.post("/api/push/subscribe")
async def subscribe(request: Request):
    sub = await request.json()
    if not isinstance(sub, dict) or not str(sub.get("endpoint", "")).startswith("https://"):
        raise HTTPException(400, "Bad subscription.")
    store.add_subscription(sub)
    return {"ok": True}


# ---- the app itself --------------------------------------------------------------
WEB = ROOT / "web"


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
