"""Bounded uploads and paths for server-generated storage keys.

Storage root is an administrator-controlled directory. Untrusted local processes
must not have write access to it; path checks are not a filesystem sandbox.
"""
import io
import os
import re
import stat
from pathlib import Path
from threading import BoundedSemaphore

from anyio import fail_after
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.responses import JSONResponse

from lifepilot.config import settings

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_MULTIPART_OVERHEAD = 64 * 1024
PHOTO_FORMATS = {"JPEG", "PNG", "WEBP"}
OWNER_KEY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FILE_KEY = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{1,5}")
PHOTO_KEY = re.compile(r"[0-9a-f]{32}\.jpg")
PHOTO_ROUTE = re.compile(r"/api/(?:people/[^/]+/photo|events/[^/]+/photos)/?")


def storage_path(kind: str, key: str, owner: str | None = None) -> Path:
    if kind not in {"attachments", "people", "event-photos"}:
        raise ValueError("Unknown storage kind")
    pattern = FILE_KEY if kind == "attachments" else PHOTO_KEY
    if not pattern.fullmatch(key) or (kind == "attachments" and (owner is None or not OWNER_KEY.fullmatch(owner))):
        raise HTTPException(409,"Ungültiger gespeicherter Dateischlüssel")
    root=Path(settings.data_dir).resolve()
    parts=[kind,owner,key] if kind=="attachments" else [kind,key]
    path=root
    for i,part in enumerate(parts):
        path=path/part
        try:
            mode=path.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise HTTPException(409,"Dateispeicher nicht verfügbar") from None
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) if i==len(parts)-1 else stat.S_ISDIR(mode)):
            raise HTTPException(409,"Unsicherer Dateispeicherpfad")
    return path


def store_new(path: Path, contents: bytes):
    """Exclusive create, private permissions, cleanup on write failure."""
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(contents)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def inspect_image(contents: bytes, expected: str | None = None, normalize: bool = False):
    try:
        with Image.open(io.BytesIO(contents),formats=list(PHOTO_FORMATS)) as image:
            if image.format not in PHOTO_FORMATS or (expected and image.format!=expected):
                raise HTTPException(415,"Bildformat stimmt nicht mit Dateiendung überein")
            if image.width*image.height>MAX_PIXELS or getattr(image,"n_frames",1)!=1:
                raise HTTPException(415,"Nur Einzelbilder bis 25 Megapixel werden unterstützt")
            image.load()
            if not normalize:
                return Image.MIME[image.format]
            image=ImageOps.exif_transpose(image)
            image.thumbnail((2048,2048))
            # New raster strips source EXIF, GPS, comments and other metadata.
            normalized=Image.new("RGB",image.size)
            normalized.paste(image.convert("RGB"))
            output=io.BytesIO()
            normalized.save(output,format="JPEG",quality=88,optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombError):
        raise HTTPException(415,"Die Datei ist kein gültiges Bild") from None


class UploadBodyLimit:
    """Limit raw multipart bytes before Starlette spools/parses them.

    At most two bounded upload requests per API process. Other endpoints retain
    their own limits. The upload slot also covers the subsequent handler.
    """
    slots=BoundedSemaphore(2)

    def __init__(self,app):
        self.app=app

    async def __call__(self,scope,receive,send):
        path=scope.get("path","")
        if scope["type"]!="http" or scope.get("method")!="POST":
            return await self.app(scope,receive,send)
        if path.rstrip("/") == "/api/attachments":
            limit=MAX_ATTACHMENT_BYTES+MAX_MULTIPART_OVERHEAD
        elif PHOTO_ROUTE.fullmatch(path):
            limit=MAX_PHOTO_BYTES+MAX_MULTIPART_OVERHEAD
        else:
            return await self.app(scope,receive,send)
        async def reject(status,message):
            return await JSONResponse({"detail":message},status_code=status,headers={"Cache-Control":"no-store"})(scope,receive,send)
        headers=dict(scope["headers"])
        if b"content-length" in headers:
            try:
                length=int(headers[b"content-length"])
                if length<0:
                    raise ValueError()
            except ValueError:
                return await reject(400,"Ungültige Upload-Größe")
            if length>limit:
                return await reject(413,"Upload zu groß")
        if not self.slots.acquire(blocking=False):
            return await reject(429,"Zu viele gleichzeitige Uploads")
        try:
            data=bytearray()
            try:
                with fail_after(60):
                    while True:
                        msg=await receive()
                        if msg["type"]=="http.disconnect":
                            return
                        chunk=msg.get("body",b"")
                        if len(data)+len(chunk)>limit:
                            return await reject(413,"Upload zu groß")
                        data.extend(chunk)
                        if not msg.get("more_body",False):
                            break
            except TimeoutError:
                return await reject(408,"Upload hat zu lange gedauert")
            # Replay bounded chunks rather than materializing a second full copy.
            offset=0
            sent=False
            async def replay():
                nonlocal offset,sent
                if sent:
                    return await receive()
                chunk=bytes(data[offset:offset+65536])
                offset+=len(chunk)
                sent=offset>=len(data)
                return {"type":"http.request","body":chunk,"more_body":not sent}
            return await self.app(scope,replay,send)
        finally:
            self.slots.release()
