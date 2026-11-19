"""Admin pages (/admin, /admin/login) and login/logout API."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .. import auth, config

router = APIRouter()
ADMIN_DIR = config.FRONTEND_DIR / "admin"


class Login(BaseModel):
    email: str
    password: str


@router.get("/admin")
def admin_dashboard(request: Request):
    if not auth.is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    return FileResponse(ADMIN_DIR / "dashboard.html", headers={"Cache-Control": "no-store"})


@router.get("/admin/login")
def admin_login_page(request: Request):
    if auth.is_admin(request):
        return RedirectResponse("/admin", status_code=302)
    return FileResponse(ADMIN_DIR / "login.html")


@router.post("/api/admin/login")
def login(body: Login):
    if not config.ADMIN_EMAIL or not config.ADMIN_PASSWORD:
        return JSONResponse({"success": False, "error": "Admin is not set up. Set ADMIN_EMAIL and ADMIN_PASSWORD in .env."}, 503)
    if not auth.credentials_ok(body.email, body.password):
        return JSONResponse({"success": False, "error": "Wrong email or password."}, 401)
    resp = JSONResponse({"success": True})
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=config.SESSION_HOURS * 3600,
                    httponly=True, samesite="lax")   # add secure=True when served over HTTPS
    return resp


@router.post("/api/admin/logout")
def logout():
    resp = JSONResponse({"success": True})
    resp.delete_cookie(auth.COOKIE)
    return resp
