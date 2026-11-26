import json
from io import BytesIO
from urllib.error import URLError

from lifepilot import voice_routes
from lifepilot.config import settings

WAV = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"fake test audio"


def enable(monkeypatch):
    monkeypatch.setattr(settings, "transcription_base_url", "http://whisper.invalid/v1")
    monkeypatch.setattr(settings, "transcription_model", "whisper-test")
    monkeypatch.setattr(settings, "transcription_api_key", "test-only-key")


def test_voice_transcript_is_preview_only(client, auth, monkeypatch):
    enable(monkeypatch)
    calls = []

    def provider(request, timeout):
        calls.append((request, timeout))
        return BytesIO(json.dumps({"text": "  Ich habe Anna Unterlagen versprochen.  "}).encode())

    monkeypatch.setattr(voice_routes, "urlopen", provider)
    before = client.get("/api/captures", headers=auth).json()
    status = client.get("/api/voice/status", headers=auth)
    assert status.json() == {"enabled": True, "max_audio_bytes": 10 * 1024 * 1024}
    assert client.get("/api/voice/status").status_code == 401
    assert client.post("/api/voice/transcribe", content=WAV, headers={"Content-Type": "audio/wav"}).status_code == 401
    assert not calls
    response = client.post("/api/voice/transcribe", headers={**auth, "Content-Type": "audio/wav"}, content=WAV)
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "Ich habe Anna Unterlagen versprochen."}
    assert client.get("/api/captures", headers=auth).json() == before
    request, timeout = calls[0]
    assert request.full_url == "http://whisper.invalid/v1/audio/transcriptions"
    assert request.get_header("Authorization") == "Bearer test-only-key"
    assert "multipart/form-data; boundary=" in request.get_header("Content-type")
    assert b'filename="recording.wav"' in request.data
    assert b"whisper-test" in request.data and WAV in request.data
    assert timeout == settings.transcription_timeout_seconds


def test_voice_validates_input_and_reports_safe_errors(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "transcription_base_url", "")
    headers = {**auth, "Content-Type": "audio/wav"}
    assert client.get("/api/voice/status", headers=auth).json()["enabled"] is False
    assert client.post("/api/voice/transcribe", headers=headers, content=WAV).status_code == 503
    enable(monkeypatch)
    calls = []
    monkeypatch.setattr(voice_routes, "urlopen", lambda *args, **kwargs: calls.append(args))
    assert client.post("/api/voice/transcribe", headers={**auth, "Content-Type": "text/plain"}, content=WAV).status_code == 415
    assert client.post("/api/voice/transcribe", headers=headers, content=b"not audio").status_code == 422
    monkeypatch.setattr(voice_routes, "MAX_AUDIO_BYTES", 32)
    assert client.post("/api/voice/transcribe", headers=headers, content=WAV * 2).status_code == 413
    assert client.post("/api/voice/transcribe", headers=headers, content=iter([WAV, WAV])).status_code == 413
    assert not calls
    monkeypatch.setattr(voice_routes, "urlopen", lambda *args, **kwargs: BytesIO(b'{"text":"  "}'))
    assert client.post("/api/voice/transcribe", headers=headers, content=WAV).status_code == 422
    monkeypatch.setattr(voice_routes, "urlopen", lambda *args, **kwargs: BytesIO(b'{"text":5}'))
    assert client.post("/api/voice/transcribe", headers=headers, content=WAV).status_code == 502
    def unavailable(*args, **kwargs):
        raise URLError("private provider details")
    monkeypatch.setattr(voice_routes, "urlopen", unavailable)
    failed = client.post("/api/voice/transcribe", headers=headers, content=WAV)
    assert failed.status_code == 502
    assert "private provider details" not in failed.text
    # Failed calls must not exhaust the concurrency limit.
    monkeypatch.setattr(voice_routes, "urlopen", lambda *args, **kwargs: BytesIO(b'{"text":"OK"}'))
    assert client.post("/api/voice/transcribe", headers=headers, content=WAV).status_code == 200


def test_voice_accepts_browser_recording_formats(client, auth, monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(voice_routes, "urlopen", lambda *args, **kwargs: BytesIO(b'{"text":"OK"}'))
    for mime, data in [("audio/webm;codecs=opus", b"\x1a\x45\xdf\xa3test"), ("audio/ogg", b"OggStest"), ("audio/mp4", b"\x00\x00\x00\x18ftypm4a ")]:
        assert client.post("/api/voice/transcribe", headers={**auth, "Content-Type": mime}, content=data).status_code == 200
