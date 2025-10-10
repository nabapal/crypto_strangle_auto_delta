from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..schemas.user import AuthResponse, UserCreate, UserLogin, UserRead
from ..services.auth_service import AuthService
from .deps import get_current_active_user, get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserCreate, session: AsyncSession = Depends(get_db_session)):
    service = AuthService(session)
    return await service.create_user(payload)


@router.post("/login", response_model=AuthResponse)
async def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db_session),
):
    service = AuthService(session)
    payload = UserLogin(email=form_data.username, password=form_data.password)
    return await service.authenticate(payload)


@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: User = Depends(get_current_active_user)):
    return UserRead.model_validate(current_user)