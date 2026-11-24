"""Authentication primitives: password hashing and JWT issuance."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User

logger = logging.getLogger(__name__)

settings = get_settings()

# A production deployment must provide JWT_SECRET (validated at startup).  In
# development an ephemeral random secret avoids a guessable hard-coded default.
_SECRET_KEY = settings.jwt_secret or secrets.token_urlsafe(48)
if not settings.jwt_secret:
    logger.warning("No JWT_SECRET configured; using an ephemeral development secret.")

ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_secret_key() -> str:
    return _SECRET_KEY


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    # bcrypt only considers the first 72 bytes; reject longer secrets instead of
    # silently truncating them.
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password is too long (maximum 72 bytes).")
    return pwd_context.hash(password)


def _encode(data: dict, token_type: str, expires: datetime) -> str:
    payload = dict(data)
    if "sub" in payload:
        payload["sub"] = str(payload["sub"])
    payload.update({"exp": expires, "iat": datetime.now(timezone.utc), "type": token_type})
    return jwt.encode(payload, _SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return _encode(data, "access", expire)


def create_refresh_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return _encode(data, "refresh", expire)


def verify_token(token: str, token_type: str = "access") -> Optional[dict]:
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        logger.info("JWT verification failed: %s", type(exc).__name__)
        return None
    if payload.get("type") != token_type:
        return None
    return payload


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_user(db: Session, email: str, password: str, full_name: str) -> User:
    user = User(
        email=email.lower().strip(),
        hashed_password=get_password_hash(password),
        full_name=full_name.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
