import json
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.request import Request as ProviderRequest, urlopen
from uuid import uuid4

from anyio import fail_after
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from lifepilot.config import settings
from lifepilot.models import User
from lifepilot.security import current_user

router = APIRouter(prefix="/api/voice", tags=["Spracheingabe"])
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 20000
MAX_RESPONSE_BYTES = 256 * 1024
# Bound concurrent in-memory audio buffers and provider calls per API process.
slots = BoundedSemaphore(2)
FORMATS = {
    "audio/webm": ("webm", "audio/webm"),
    "video/webm": ("webm", "audio/webm"),
    "audio/ogg": ("ogg", "audio/ogg"),
    "audio/mp4": ("m4a", "audio/mp4"),
    "video/mp4": ("m4a", "audio/mp4"),
    "audio/x-m4a": ("m4a", "audio/mp4"),
    "audio/mpeg": ("mp3", "audio/mpeg"),
    "audio/wav": ("wav", "audio/wav"),
    "audio/x-wav": ("wav", "audio/wav"),
    "audio/flac": ("flac", "audio/flac"),
    "audio/x-flac": ("flac", "audio/flac"),
}


class VoiceStatus(BaseModel):
    enabled: bool
    max_audio_bytes: int


class Transcript(BaseModel):
    text: str


def configured():
    return bool(settings.transcription_base_url.strip() and settings.transcription_model.strip())


def recognizable(data: bytes, extension: str) -> bool:
    if extension == "webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if extension == "ogg":
        return data.startswith(b"OggS")
    if extension == "m4a":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if extension == "wav":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if extension == "flac":
        return data.startswith(b"fLaC")
    if extension == "mp3":
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224)
    return False


def transcribe(data: bytes, extension: str, media_type: str) -> str:
    boundary = uuid4().hex
    def field(name: str, value: str) -> bytes:
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
    body = (
        field("model", settings.transcription_model)
        + field("response_format", "json")
        + (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"recording.{extension}\"\r\nContent-Type: {media_type}\r\n\r\n").encode()
        + data + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"}
    if settings.transcription_api_key:
        headers["Authorization"] = f"Bearer {settings.transcription_api_key}"
    try:
        request = ProviderRequest(f"{settings.transcription_base_url.rstrip('/')}/audio/transcriptions", data=body, headers=headers, method="POST")
        with urlopen(request, timeout=settings.transcription_timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Response too large")
        text = json.loads(raw)["text"]
        if not isinstance(text, str) or len(text.strip()) > MAX_TEXT_LENGTH:
            raise ValueError("Invalid transcription")
        return text.strip()
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "Spracherkennung nicht erreichbar oder ungültige Antwort. Die Aufnahme kann erneut gesendet werden.") from None


@router.get("/status", response_model=VoiceStatus)
def voice_status(user: User = Depends(current_user)):
    return VoiceStatus(enabled=configured(), max_audio_bytes=MAX_AUDIO_BYTES)


@router.post("/transcribe", response_model=Transcript)
async def voice_transcribe(request: Request, user: User = Depends(current_user)):
    if not configured():
        raise HTTPException(503, "Spracherkennung ist nicht konfiguriert")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in FORMATS:
        raise HTTPException(415, "Audioformat wird nicht unterstützt")
    extension, normalized_type = FORMATS[media_type]
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise HTTPException(400, "Ungültige Dateigröße") from None
        if size < 0:
            raise HTTPException(400, "Ungültige Dateigröße")
        if size > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio darf höchstens 10 MiB groß sein")
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Die Spracherkennung ist gerade ausgelastet")
    try:
        data = bytearray()
        try:
            with fail_after(60):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > MAX_AUDIO_BYTES:
                        raise HTTPException(413, "Audio darf höchstens 10 MiB groß sein")
                    data.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Audio-Upload hat zu lange gedauert") from None
        if not recognizable(data, extension):
            raise HTTPException(422, "Die Datei enthält kein erkennbares Audioformat")
        text = await run_in_threadpool(transcribe, bytes(data), extension, normalized_type)
        if not text:
            raise HTTPException(422, "Es wurde kein Text erkannt")
        return Transcript(text=text)
    finally:
        slots.release()
