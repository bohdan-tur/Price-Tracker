from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def _create_token(data: dict, expires_delta: timedelta, secret_key: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret_key, algorithm=settings.ALGORITHM)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES)
    return _create_token(data, delta, settings.ACCESS_TOKEN_SECRET_KEY)


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    delta = expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS)
    return _create_token(data, delta, settings.REFRESH_TOKEN_SECRET_KEY)


def _verify_token(token: str, secret_key: str) -> int:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret_key, algorithms=[settings.ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        return int(user_id_str)
    except (jwt.InvalidTokenError, ValueError) as e:
        raise credentials_exception from e


def verify_access_token(token: str) -> int:
    return _verify_token(token, settings.ACCESS_TOKEN_SECRET_KEY)


def verify_refresh_token(token: str) -> int:
    return _verify_token(token, settings.REFRESH_TOKEN_SECRET_KEY)
