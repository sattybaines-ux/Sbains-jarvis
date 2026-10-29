"""Settings, read from environment variables (GitHub Actions secrets/variables)."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _saved(name: str) -> str:
    f = ROOT / "out" / name
    return f.read_text().strip() if f.exists() else ""


@dataclass
class Config:
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo(env("TIMEZONE", "America/Toronto")))
    user_name: str = field(default_factory=lambda: env("USER_NAME", "Satty"))
    model: str = field(default_factory=lambda: env("CLAUDE_MODEL", "claude-opus-5-5"))
    chat_model: str = field(default_factory=lambda: env("CHAT_MODEL", "claude-opus-5-5"))

    ms_client_id: str = field(default_factory=lambda: env("MS_CLIENT_ID"))
    ms_tenant: str = field(default_factory=lambda: env("MS_TENANT_ID", "organizations"))
    # Microsoft rotates this token on every use; a long-running server keeps the newest one in out/.
    ms_refresh_token: str = field(default_factory=lambda: _saved("ms_refresh_token") or env("MS_REFRESH_TOKEN"))

    google_client_id: str = field(default_factory=lambda: env("GOOGLE_CLIENT_ID"))
    google_client_secret: str = field(default_factory=lambda: env("GOOGLE_CLIENT_SECRET"))
    google_refresh_token: str = field(default_factory=lambda: env("GOOGLE_REFRESH_TOKEN"))

    notion_token: str = field(default_factory=lambda: env("NOTION_TOKEN"))

    fish_api_key: str = field(default_factory=lambda: env("FISH_AUDIO_API_KEY"))
    fish_voice_id: str = field(default_factory=lambda: env("FISH_AUDIO_VOICE_ID"))

    passphrase: str = field(default_factory=lambda: env("BRIEF_PASSPHRASE"))
    vapid_public_key: str = field(default_factory=lambda: env("VAPID_PUBLIC_KEY"))
    vapid_private_key: str = field(default_factory=lambda: env("VAPID_PRIVATE_KEY"))
    vapid_subject: str = field(default_factory=lambda: env("VAPID_SUBJECT", "mailto:me@example.com"))
    push_subscriptions: str = field(default_factory=lambda: env("PUSH_SUBSCRIPTIONS"))

    out_dir: Path = ROOT / "out"      # private files (never published)
    site_dir: Path = ROOT / "site"    # what gets deployed to GitHub Pages

    @property
    def profile(self) -> str:
        return (ROOT / "config" / "profile.md").read_text(encoding="utf-8")
