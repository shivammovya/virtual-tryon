"""Very small admin auth: email+password from .env, signed cookie session."""
import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from . import config

COOKIE = "admin_session"


def credentials_ok(email: str, password: str) -> bool:
    """Constant-time check against ADMIN_EMAIL / ADMIN_PASSWORD from .env."""
    if not config.ADMIN_EMAIL or not config.ADMIN_PASSWORD:
        return False  # admin disabled until the owner sets credentials
    e_ok = hmac.compare_digest(email.strip().lower().encode(), config.ADMIN_EMAIL.encode())
    p_ok = hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode())
    return e_ok and p_ok


def _sign(expiry: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), expiry.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    expiry = str(int(time.time()) + config.SESSION_HOURS * 3600)
    return f"{expiry}.{_sign(expiry)}"


def is_admin(request: Request) -> bool:
    token = request.cookies.get(COOKIE, "")
    expiry, _, sig = token.partition(".")
    if not expiry.isdigit() or not hmac.compare_digest(sig, _sign(expiry)):
        return False
    return int(expiry) > time.time()


def require_admin(request: Request) -> None:
    """FastAPI dependency: protects admin-only API routes."""
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Please log in as the store owner.")
