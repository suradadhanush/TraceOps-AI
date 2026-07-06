"""
Auth API Routes — FIXED VERSION

Bug fixed: LOGIN_HTML.format() was crashing with KeyError because the embedded
CSS contains curly braces (e.g. `{box-sizing: border-box}`) which Python's
str.format() tries to interpret as placeholders. Replaced with placeholder
tokens + .replace() which is brace-safe.

GET  /auth/login/github          → redirect to GitHub OAuth
GET  /auth/callback/github       → handle GitHub callback
GET  /auth/login/google          → redirect to Google OAuth
GET  /auth/callback/google       → handle Google callback
GET  /auth/me                    → current user info
POST /auth/logout                → destroy session
GET  /auth/login                 → login page HTML
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import OAuthState, User
from app.services.auth import (
    create_session,
    delete_session,
    get_user_from_session,
    upsert_github_user,
    upsert_google_user,
)
from app.api.auth.deps import SESSION_COOKIE, get_current_user, get_optional_user

router = APIRouter(prefix="/auth", tags=["Auth"])

GITHUB_AUTH_URL   = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL  = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL   = "https://api.github.com/user"
GITHUB_EMAIL_URL  = "https://api.github.com/user/emails"

GOOGLE_AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL  = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL   = "https://www.googleapis.com/oauth2/v3/userinfo"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _save_state(db: AsyncSession, provider: str, user_id: Optional[str] = None) -> str:
    state = secrets.token_urlsafe(32)
    obj   = OAuthState(
        state=state,
        provider=provider,
        user_id=user_id,
        expires_at=_now() + timedelta(minutes=10),
    )
    db.add(obj)
    await db.commit()
    return state


async def _validate_state(db: AsyncSession, state: str, provider: str) -> OAuthState:
    result = await db.execute(
        select(OAuthState)
        .where(OAuthState.state == state)
        .where(OAuthState.provider == provider)
        .where(OAuthState.expires_at > _now())
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    await db.delete(obj)
    await db.commit()
    return obj


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.SESSION_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        path="/",
    )


# ── Login page HTML ───────────────────────────────────────────────────────────
# CRITICAL FIX: This template uses __TOKEN__ style placeholders instead of
# {placeholder} because the CSS below contains literal curly braces which
# would break Python's str.format(). We use .replace() at render time instead,
# which is completely brace-safe.

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Sign in — TraceOps AI</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500&display=swap" rel="stylesheet"/>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#050816;color:#f1f5f9;min-height:100vh;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden}
.orb{position:fixed;border-radius:50%;filter:blur(80px);pointer-events:none}
.orb1{width:500px;height:500px;background:rgba(124,58,237,.08);top:-150px;left:-150px}
.orb2{width:400px;height:400px;background:rgba(6,182,212,.06);bottom:-100px;right:-100px}
.grid{position:fixed;inset:0;background-image:linear-gradient(rgba(99,102,241,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(99,102,241,.03) 1px,transparent 1px);background-size:60px 60px}
.card{background:#0b1228;border:1px solid rgba(99,102,241,.2);border-radius:20px;padding:40px;width:100%;max-width:420px;position:relative;z-index:1;box-shadow:0 24px 80px rgba(0,0,0,.6),0 0 40px rgba(124,58,237,.1)}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:32px;justify-content:center}
.logo-text{font-family:'Syne',sans-serif;font-weight:800;font-size:22px}
.logo-text span{color:#a78bfa}
h1{font-family:'Syne',sans-serif;font-size:24px;font-weight:800;text-align:center;margin-bottom:8px}
.sub{color:#94a3b8;font-size:14px;text-align:center;margin-bottom:32px;line-height:1.6}
.btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:13px 20px;border-radius:12px;font-size:14px;font-weight:600;font-family:'Syne',sans-serif;cursor:pointer;border:none;transition:all .2s;margin-bottom:12px;text-decoration:none}
.btn-github{background:#161b22;color:#f1f5f9;border:1px solid rgba(255,255,255,.1)}
.btn-github:hover{background:#21262d;border-color:rgba(167,139,250,.4);box-shadow:0 0 20px rgba(124,58,237,.2)}
.btn-google{background:#fff;color:#1f2937;border:1px solid rgba(0,0,0,.1)}
.btn-google:hover{background:#f9fafb;box-shadow:0 4px 16px rgba(0,0,0,.15)}
.divider{display:flex;align-items:center;gap:12px;margin:8px 0 20px;color:#475569;font-size:12px}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:rgba(99,102,241,.15)}
.note{font-size:12px;color:#475569;text-align:center;margin-top:24px;line-height:1.6}
.note a{color:#a78bfa}
.error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:10px;padding:12px;font-size:13px;color:#fca5a5;text-align:center;margin-bottom:16px}
</style>
</head>
<body>
<div class="grid"></div>
<div class="orb orb1"></div>
<div class="orb orb2"></div>
<div class="card">
  <div class="logo">
    <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="url(#g)"/>
      <path d="M8 16L13 11L18 16L23 10" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M8 22L12 18L16 20L20 16L24 18" stroke="#67e8f9" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="23" cy="10" r="2.5" fill="#a78bfa"/>
      <defs><linearGradient id="g" x1="0" y1="0" x2="32" y2="32"><stop stop-color="#7c3aed"/><stop offset="1" stop-color="#3b82f6"/></linearGradient></defs>
    </svg>
    <span class="logo-text">Trace<span>Ops</span> AI</span>
  </div>
  __ERROR_BLOCK__
  <h1>Welcome back</h1>
  <p class="sub">Sign in to your execution intelligence dashboard.<br/>Track commits, AI usage, and deploy velocity.</p>
  __GITHUB_BTN__
  <div class="divider">or</div>
  __GOOGLE_BTN__
  <p class="note">By signing in you agree to our terms.<br/>Your data is isolated to your account only.<br/><a href="/">← Back to home</a></p>
</div>
</body>
</html>"""

GITHUB_BTN = '<a href="/auth/login/github" class="btn btn-github"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>Continue with GitHub</a>'

GOOGLE_BTN = '<a href="/auth/login/google" class="btn btn-google"><svg width="20" height="20" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>Continue with Google</a>'

GITHUB_DISABLED = '<div class="btn btn-github" style="opacity:.4;cursor:not-allowed;pointer-events:none">🐙 GitHub OAuth (configure GITHUB_CLIENT_ID)</div>'
GOOGLE_DISABLED = '<div class="btn btn-google" style="opacity:.4;cursor:not-allowed;pointer-events:none;color:#1f2937">🔵 Google OAuth (configure GOOGLE_CLIENT_ID)</div>'


def _login_page(error: str = "") -> HTMLResponse:
    """
    FIXED: uses .replace() with unique __TOKEN__ markers instead of .format(),
    so the embedded CSS's curly braces never get misinterpreted as placeholders.
    """
    error_block = f'<div class="error">⚠️ {error}</div>' if error else ""
    github_btn  = GITHUB_BTN if settings.GITHUB_CLIENT_ID else GITHUB_DISABLED
    google_btn  = GOOGLE_BTN if settings.GOOGLE_CLIENT_ID else GOOGLE_DISABLED

    html = (
        LOGIN_HTML
        .replace("__ERROR_BLOCK__", error_block)
        .replace("__GITHUB_BTN__", github_btn)
        .replace("__GOOGLE_BTN__", google_btn)
    )
    return HTMLResponse(html)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/login", include_in_schema=False)
async def login_page(request: Request, error: str = "", db: AsyncSession = Depends(get_db)):
    user = await get_optional_user(request, db)
    if user:
        return RedirectResponse("/app/dashboard", status_code=302)
    return _login_page(error)


@router.get("/login/github")
async def github_login(db: AsyncSession = Depends(get_db)):
    if not settings.GITHUB_CLIENT_ID:
        return RedirectResponse("/auth/login?error=GitHub+OAuth+not+configured", status_code=302)
    state  = await _save_state(db, "github")
    params = urlencode({
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": f"{settings.FRONTEND_URL}/auth/callback/github",
        "scope": "read:user user:email",
        "state": state,
    })
    return RedirectResponse(f"{GITHUB_AUTH_URL}?{params}", status_code=302)


@router.get("/callback/github")
async def github_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        await _validate_state(db, state, "github")
    except HTTPException:
        return RedirectResponse("/auth/login?error=Invalid+OAuth+state", status_code=302)

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id":     settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  f"{settings.FRONTEND_URL}/auth/callback/github",
            },
            timeout=15,
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return RedirectResponse("/auth/login?error=GitHub+auth+failed", status_code=302)

        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10,
        )
        github_user = user_resp.json()

        email = github_user.get("email")
        if not email:
            email_resp = await client.get(
                GITHUB_EMAIL_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            emails = email_resp.json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            email = primary["email"] if primary else None

    user = await upsert_github_user(
        db,
        github_id=str(github_user["id"]),
        email=email or "",
        name=github_user.get("name") or github_user.get("login"),
        avatar_url=github_user.get("avatar_url"),
        username=github_user.get("login"),
    )
    await db.commit()

    token = await create_session(
        db, user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    response = RedirectResponse("/app/dashboard", status_code=302)
    _set_session_cookie(response, token)
    return response


@router.get("/login/google")
async def google_login(db: AsyncSession = Depends(get_db)):
    if not settings.GOOGLE_CLIENT_ID:
        return RedirectResponse("/auth/login?error=Google+OAuth+not+configured", status_code=302)
    state  = await _save_state(db, "google")
    params = urlencode({
        "client_id":     settings.GOOGLE_CLIENT_ID,
        "redirect_uri":  f"{settings.FRONTEND_URL}/auth/callback/google",
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "offline",
    })
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}", status_code=302)


@router.get("/callback/google")
async def google_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        await _validate_state(db, state, "google")
    except HTTPException:
        return RedirectResponse("/auth/login?error=Invalid+OAuth+state", status_code=302)

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri":  f"{settings.FRONTEND_URL}/auth/callback/google",
                "grant_type":    "authorization_code",
            },
            timeout=15,
        )
        token_data   = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return RedirectResponse("/auth/login?error=Google+auth+failed", status_code=302)

        user_resp = await client.get(
            GOOGLE_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        g_user = user_resp.json()

    user = await upsert_google_user(
        db,
        google_id=g_user.get("sub", ""),
        email=g_user.get("email", ""),
        name=g_user.get("name"),
        avatar_url=g_user.get("picture"),
    )
    await db.commit()

    token = await create_session(
        db, user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    response = RedirectResponse("/app/dashboard", status_code=302)
    _set_session_cookie(response, token)
    return response


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id":               current_user.id,
        "email":            current_user.email,
        "name":             current_user.name,
        "avatar_url":       current_user.avatar_url,
        "github_username":  current_user.github_username,
        "github_id":        current_user.github_id,
        "google_id":        current_user.google_id,
        "created_at":       current_user.created_at,
    }


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await delete_session(db, token)
        await db.commit()
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
