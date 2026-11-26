import base64
import re
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lifepilot.config import settings


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise ValueError("Invalid base64url")
    return base64.b64decode(value.rstrip("=") + "=" * (-len(value.rstrip("=")) % 4), altchars=b"-_", validate=True)


@lru_cache(maxsize=4)
def public_key(private: str, subject: str) -> str | None:
    if not private or not subject.startswith(("mailto:", "https://")):
        return None
    try:
        key = serialization.load_der_private_key(decode(private), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            return None
        return encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    except (TypeError, ValueError):
        return None


def configured_public_key() -> str | None:
    return public_key(settings.push_vapid_private_key, settings.push_vapid_subject)


if __name__ == "__main__":
    key = ec.generate_private_key(ec.SECP256R1())
    print("PUSH_VAPID_PRIVATE_KEY=" + encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
    print("PUSH_VAPID_SUBJECT=mailto:admin@example.org")
