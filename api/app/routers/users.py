from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import User
from app.users import CurrentUser

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users", response_model=list[User])
async def list_users(request: Request) -> list[User]:
    return await request.app.state.store.list_users()


@router.get("/me", response_model=User)
async def me(user: CurrentUser) -> User:
    return user
