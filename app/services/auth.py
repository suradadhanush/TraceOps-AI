"""
Auth Service

Handles:
- Session creation/validation/deletion
- User upsert from OAuth provider data
- Secure session token generation
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import User, UserSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_session_token() -> str:
    """Cryptographically secure session token."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Store hashed version in DB — never raw token."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    db: AsyncSession,
    user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Create a new session. Returns the raw session token (send to client)."""
    raw_token = generate_session_token()
    hashed    = hash_token(raw_token)
    expires   = _now() + timedelta(days=settings.SESSION_EXPIRE_DAYS)

    session = UserSession(
        user_id=user_id,
        session_token=hashed,
        expires_at=expires,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return raw_token


async def get_user_from_session(
    db: AsyncSession,
    raw_token: str,
) -> Optional[User]:
    """Validate session token and return the User. Returns None if invalid/expired."""
    if not raw_token:
        return None
    hashed = hash_token(raw_token)
    result = await db.execute(
        select(UserSession)
        .where(UserSession.session_token == hashed)
        .where(UserSession.expires_at > _now())
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    result2 = await db.execute(select(User).where(User.id == session.user_id, User.is_active == True))
    return result2.scalar_one_or_none()


async def delete_session(db: AsyncSession, raw_token: str) -> bool:
    """Logout — delete session by raw token."""
    hashed = hash_token(raw_token)
    result = await db.execute(select(UserSession).where(UserSession.session_token == hashed))
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        return True
    return False


async def upsert_github_user(
    db: AsyncSession,
    github_id: str,
    email: str,
    name: Optional[str],
    avatar_url: Optional[str],
    username: Optional[str],
) -> User:
    """Create or update user from GitHub OAuth data."""
    # Try by github_id first
    result = await db.execute(select(User).where(User.github_id == str(github_id)))
    user = result.scalar_one_or_none()

    if not user and email:
        # Try by email (might have signed in with Google before)
        result2 = await db.execute(select(User).where(User.email == email))
        user = result2.scalar_one_or_none()

    if user:
        user.github_id       = str(github_id)
        user.github_username = username
        if name:       user.name       = name
        if avatar_url: user.avatar_url = avatar_url
    else:
        user = User(
            email=email or f"github_{github_id}@traceops.local",
            name=name,
            avatar_url=avatar_url,
            github_id=str(github_id),
            github_username=username,
        )
        db.add(user)

    await db.flush()
    return user


async def upsert_google_user(
    db: AsyncSession,
    google_id: str,
    email: str,
    name: Optional[str],
    avatar_url: Optional[str],
) -> User:
    """Create or update user from Google OAuth data."""
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user and email:
        result2 = await db.execute(select(User).where(User.email == email))
        user = result2.scalar_one_or_none()

    if user:
        user.google_id = google_id
        if name:       user.name       = name
        if avatar_url: user.avatar_url = avatar_url
    else:
        user = User(
            email=email,
            name=name,
            avatar_url=avatar_url,
            google_id=google_id,
        )
        db.add(user)

    await db.flush()
    return user
