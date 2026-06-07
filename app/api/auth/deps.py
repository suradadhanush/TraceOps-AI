"""
Auth Dependencies

FastAPI dependencies for protected routes.
"""
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import User
from app.services.auth import get_user_from_session

SESSION_COOKIE = "traceops_session"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require authenticated user. Raises 401 if not authenticated."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        # Also check Authorization header for API clients
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please sign in at /auth/login",
        )

    user = await get_user_from_session(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again.",
        )
    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Return user if authenticated, None otherwise. For pages that work both ways."""
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None
