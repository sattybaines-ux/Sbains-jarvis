"""Fish Audio text-to-speech -> MP3 bytes."""
import requests


def speak(text: str, api_key: str, voice_id: str) -> bytes:
    body = {"text": text, "format": "mp3"}
    if voice_id:
        body["reference_id"] = voice_id
    r = requests.post("https://api.fish.audio/v1/tts", json=body, timeout=180,
                      headers={"Authorization": f"Bearer {api_key}", "model": "s1"})
    if r.status_code != 200:
        raise RuntimeError(f"Fish Audio returned {r.status_code}: {r.text[:200]}")
    if not r.content.startswith((b"ID3", b"\xff")):
        raise RuntimeError("Fish Audio did not return MP3 audio.")
    return r.content
