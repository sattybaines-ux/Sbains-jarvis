"""Voice: speech-to-text on the server (Whisper, free, runs locally) and text-to-speech via Fish Audio."""
import io
import os
import threading

from agent.config import Config

_model = None
_model_lock = threading.Lock()


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(os.environ.get("WHISPER_MODEL", "base.en"), device="cpu", compute_type="int8")
        return _model


def warm_up() -> None:
    try:
        _whisper()
    except Exception as e:  # voice input is optional; typing still works
        print("Whisper not available:", e)


def transcribe(audio: bytes) -> str:
    segments, _ = _whisper().transcribe(io.BytesIO(audio), beam_size=1, vad_filter=True, language="en")
    return " ".join(s.text.strip() for s in segments).strip()


def speak(text: str) -> bytes | None:
    """MP3 from Fish Audio, or None so the phone uses its own built-in voice."""
    cfg = Config()
    if not cfg.fish_api_key:
        return None
    from agent.voice import speak as fish
    return fish(text, cfg.fish_api_key, cfg.fish_voice_id)
