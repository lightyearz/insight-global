"""Identity without auth: ``X-User-Id`` header, defaulting to ``admin`` (docs/CONTRACT.md section 3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.schemas import DEFAULT_USER_ID, Briefing, User


async def current_user(request: Request, x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None) -> User:
    user_id = (x_user_id or "").strip() or DEFAULT_USER_ID
    user = await request.app.state.store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown user '{user_id[:64]}'")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def can_modify(user: User, briefing: Briefing) -> bool:
    """Review/delete permission: admins always; analysts only their own briefings."""
    return user.role == "admin" or briefing.created_by == user.id
