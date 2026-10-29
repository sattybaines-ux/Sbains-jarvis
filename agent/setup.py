"""One-time connections, run from the "Connect accounts" GitHub workflow (or locally).

Tokens are written straight into GitHub secrets with `gh secret set`; they are never printed,
because Actions logs on a public repo are public.

  python -m agent.setup microsoft          # device-code sign-in; follow the code shown in the log
  python -m agent.setup google-start       # prints the Google consent link
  python -m agent.setup google-finish CODE # exchanges the code from the localhost redirect
  python -m agent.setup push-keys          # creates the VAPID keys for iPhone notifications
"""
import base64
import subprocess
import sys
import time
from urllib.parse import unquote, urlencode

import requests

from .config import Config
from .sources import google as g
from .sources import outlook as o


def save_secret(name: str, value: str) -> None:
    subprocess.run(["gh", "secret", "set", name], input=value.encode(), check=True)
    print(f"Saved secret {name}.")


def save_variable(name: str, value: str) -> None:
    subprocess.run(["gh", "variable", "set", name, "--body", value], check=True)
    print(f"Saved variable {name}.")


def microsoft(cfg: Config) -> None:
    base = f"https://login.microsoftonline.com/{cfg.ms_tenant}/oauth2/v2.0"
    dc = requests.post(f"{base}/devicecode", data={"client_id": cfg.ms_client_id, "scope": o.SCOPES}, timeout=30).json()
    if "user_code" not in dc:
        sys.exit(f"Microsoft refused: {dc.get('error_description', dc)}")
    print("=" * 60)
    print(f"On your phone, open {dc['verification_uri']} and enter code:  {dc['user_code']}")
    print("=" * 60, flush=True)
    deadline = time.time() + dc["expires_in"]
    while time.time() < deadline:
        time.sleep(dc.get("interval", 5))
        tok = requests.post(f"{base}/token", timeout=30, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cfg.ms_client_id, "device_code": dc["device_code"]}).json()
        if "refresh_token" in tok:
            save_secret("MS_REFRESH_TOKEN", tok["refresh_token"])
            print("Microsoft 365 connected.")
            return
        if tok.get("error") not in ("authorization_pending", "slow_down"):
            sys.exit(f"Microsoft sign-in failed: {tok.get('error_description', tok)}")
    sys.exit("Timed out waiting for sign-in.")


def google_start(cfg: Config) -> None:
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": cfg.google_client_id, "redirect_uri": "http://localhost", "response_type": "code",
        "scope": " ".join(g.SCOPES), "access_type": "offline", "prompt": "consent"})
    print("Open this link, approve, and you'll land on a page that won't load (that's expected).")
    print("Copy everything after 'code=' up to '&scope' from the address bar, then run 'google-finish'.\n")
    print(url)


def google_finish(cfg: Config, code: str) -> None:
    code = unquote(code.split("code=")[-1].split("&")[0].strip())
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "code": code, "client_id": cfg.google_client_id, "client_secret": cfg.google_client_secret,
        "redirect_uri": "http://localhost", "grant_type": "authorization_code"}).json()
    if "refresh_token" not in tok:
        sys.exit(f"Google refused: {tok.get('error_description', tok.get('error', tok))}")
    save_secret("GOOGLE_REFRESH_TOKEN", tok["refresh_token"])
    print("Google connected.")


def push_keys() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    save_secret("VAPID_PRIVATE_KEY", b64u(private_raw))
    save_variable("VAPID_PUBLIC_KEY", b64u(public_raw))


if __name__ == "__main__":
    cfg = Config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "microsoft":
        microsoft(cfg)
    elif cmd == "google-start":
        google_start(cfg)
    elif cmd == "google-finish":
        google_finish(cfg, sys.argv[2])
    elif cmd == "push-keys":
        push_keys()
    else:
        sys.exit(__doc__)
