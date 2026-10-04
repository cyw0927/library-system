"""Opaque, revocable sessions and salted scrypt passwords (never reversible)."""
import hashlib
import re
import secrets
from datetime import datetime, timezone
from threading import BoundedSemaphore

# OWASP scrypt minimum; bound concurrent work to keep memory consumption finite.
PASSWORD_SLOTS = BoundedSemaphore(2)
N, R, P = 2**17, 8, 1
MAXMEM = 256 * 1024 * 1024


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def username(value):
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", normalized) or normalized == "local":
        raise ValueError("Use 3–64 ASCII letters/digits/._-; local is reserved")
    return normalized


def hash_password(password):
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters")
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, maxmem=MAXMEM, dklen=32)
    return f"scrypt${salt.hex()}${result.hex()}"


def verify_password(password, encoded):
    # Even unknown/disabled accounts incur the same bounded expensive calculation.
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if algorithm != "scrypt" or len(salt) != 16 or len(expected) != 32:
            raise ValueError
    except (ValueError, AttributeError):
        salt, expected = bytes(16), bytes(32)
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, maxmem=MAXMEM, dklen=32)
    return secrets.compare_digest(actual, expected)


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()
