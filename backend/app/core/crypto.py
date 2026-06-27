from __future__ import annotations
import base64
from functools import lru_cache
from cryptography.fernet import Fernet, MultiFernet
from .config import settings


# Default JWT secret shipped in config.py. The packaged desktop app runs with no
# .env, so it falls back to this value and derives its Fernet key from it. We
# MUST keep it in the decryption candidate set so secrets written by the
# packaged app (default key) still decrypt when the same DB is opened by a dev
# process that has an explicit ENCRYPTION_KEY / different JWT_SECRET in .env.
_DEFAULT_JWT_SECRET = "change-me-in-production"


def _derive_key(jwt_secret: str) -> str:
    """Deterministically derive a urlsafe-base64 Fernet key from a JWT secret."""
    raw = (jwt_secret + "-h3c-fernet").encode()[:32].ljust(32, b"0")
    return base64.urlsafe_b64encode(raw).decode()


@lru_cache(maxsize=1)
def _candidate_keys() -> tuple[str, ...]:
    """Ordered, de-duplicated list of Fernet keys to try.

    The FIRST key is the *primary* used for encryption. All keys are tried (in
    order) for decryption via MultiFernet, so a secret encrypted under any of
    these keys — across dev (.env) and packaged (defaults) environments — still
    decrypts. This makes API keys portable between the two run modes that share
    the same ~/.h3c-agent/app.db.
    """
    keys: list[str] = []
    # 1) explicit ENCRYPTION_KEY (production / .env) — primary when present.
    if settings.ENCRYPTION_KEY:
        keys.append(settings.ENCRYPTION_KEY)
    # 2) derived from the configured JWT_SECRET (dev fallback when no explicit key).
    keys.append(_derive_key(settings.JWT_SECRET))
    # 3) derived from the built-in default JWT_SECRET (the packaged app's key).
    keys.append(_derive_key(_DEFAULT_JWT_SECRET))
    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return tuple(out)


@lru_cache(maxsize=1)
def _get_multifernet() -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in _candidate_keys()])


def encrypt_str(plaintext: str) -> str:
    if plaintext is None:
        return ""
    # MultiFernet encrypts with its first (primary) key.
    return _get_multifernet().encrypt(plaintext.encode()).decode()


def decrypt_str(token: str) -> str:
    if not token:
        return ""
    # MultiFernet tries every candidate key; raises InvalidToken only if none match.
    return _get_multifernet().decrypt(token.encode()).decode()
