from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import create_access_token, get_password_hash, verify_password
from ..models import User
from ..schemas.user import AuthResponse, UserCreate, UserLogin, UserRead


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def create_user(self, payload: UserCreate) -> UserRead:
        existing = await self.get_user_by_email(payload.email)
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")

        user = User(
            email=payload.email.lower(),
            full_name=payload.full_name,
            hashed_password=get_password_hash(payload.password),
            is_active=True,
            is_superuser=False,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return UserRead.model_validate(user)

    async def authenticate(self, payload: UserLogin) -> AuthResponse:
        user = await self.get_user_by_email(payload.email)
        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

        token = create_access_token(subject=str(user.id))
        return AuthResponse(access_token=token, user=UserRead.model_validate(user))

    async def ensure_initial_superuser(self, email: str | None, password: str | None) -> None:
        if not email or not password:
            return
        existing = await self.get_user_by_email(email)
        if existing:
            return
        user = User(
            email=email.lower(),
            hashed_password=get_password_hash(password),
            is_active=True,
            is_superuser=True,
        )
        self.session.add(user)
        await self.session.commit()

    async def get_user_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)
