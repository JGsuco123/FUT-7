from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, expected = stored_hash.split("$", maxsplit=1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310_000).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def normalize_team_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.strip().casefold())
    ascii_name = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(ascii_name.split())


def is_valid_invite_pin(pin: str) -> bool:
    return pin.isascii() and pin.isdigit() and 6 <= len(pin) <= 12
