    from __future__ import annotations

    import logging
    import time

    from fastapi import APIRouter, Depends, HTTPException, status
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.database import get_db
    from app.middlewares.auth_middleware import get_current_user
    from app.models.user import User
    from app.schemas.auth import Token, TokenRefresh, UserLogin, UserRegister, UserResponse
    from app.services.auth import (
        create_access_token,
        create_refresh_token,
        create_user,
        get_user_by_email,
        verify_password,
        verify_token,
    )

    router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
    logger = logging.getLogger(__name__)

    # Reused verbatim for every credential failure so the response never reveals
    # whether the email exists or the password was wrong.
    INVALID_CREDENTIALS = "Incorrect email or password"


    def _mask_email(email: str) -> str:
        """Safe diagnostic form of an address: ``a***@example.com``."""
        email = (email or "").strip()
        if "@" not in email:
            return "***"
        local, _, domain = email.partition("@")
        return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


    def _log_auth_failure(
        stage: str,
        category: str,
        status_code: int,
        started: float,
        email: str = "",
    ) -> None:
        """Log one authentication failure with safe context only.

        The request id is injected by the logging filter, so no credentials,
        tokens or full addresses are ever written.
        """
        logger.warning(
            "auth failure stage=%s category=%s status=%s email=%s duration_ms=%s",
            stage,
            category,
            status_code,
            _mask_email(email),
            int((time.perf_counter() - started) * 1000),
        )


    @router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    def register(user_data: UserRegister, db: Session = Depends(get_db)):
        """Create a unified account (no doctor/student role)."""
        started = time.perf_counter()
        try:
            user = create_user(
                db=db,
                email=user_data.email,
                password=user_data.password,
                full_name=user_data.full_name,
            )
            return user
        except ValueError as exc:
            _log_auth_failure("register", "invalid_password", 400, started, user_data.email)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except IntegrityError:
            db.rollback()
            _log_auth_failure("register", "email_exists", 400, started, user_data.email)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
            )
        except Exception:
            db.rollback()
            logger.exception("auth failure stage=register category=internal_error")
            raise


    @router.post("/login", response_model=Token)
    def login(credentials: UserLogin, db: Session = Depends(get_db)):
        started = time.perf_counter()
        try:
            user = get_user_by_email(db, credentials.email)

            if user is None:
                _log_auth_failure("login", "unknown_email", 401, started, credentials.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=INVALID_CREDENTIALS,
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if not user.is_active:
                _log_auth_failure("login", "inactive_account", 403, started, credentials.email)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is unavailable; contact support",
                )

            if not verify_password(credentials.password, user.hashed_password):
                _log_auth_failure("login", "invalid_password", 401, started, credentials.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=INVALID_CREDENTIALS,
                    headers={"WWW-Authenticate": "Bearer"},
                )

            tokens = {
                "access_token": create_access_token(data={"sub": user.id}),
                "refresh_token": create_refresh_token(data={"sub": user.id}),
                "token_type": "bearer",
            }
            logger.info(
                "auth success stage=login user_id=%s duration_ms=%s",
                user.id,
                int((time.perf_counter() - started) * 1000),
            )
            return tokens
        except HTTPException:
            raise
        except Exception:
            logger.exception("auth failure stage=login category=internal_error")
            raise


    @router.post("/refresh", response_model=Token)
    def refresh_token(token_data: TokenRefresh, db: Session = Depends(get_db)):
        started = time.perf_counter()
        payload = verify_token(token_data.refresh_token, token_type="refresh")
        if payload is None:
            _log_auth_failure("refresh", "invalid_refresh_token", 401, started)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
            )
        try:
            user_id = int(payload.get("sub", ""))
        except (TypeError, ValueError):
            _log_auth_failure("refresh", "invalid_token_payload", 401, started)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            _log_auth_failure("refresh", "user_unavailable", 401, started)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return {
            "access_token": create_access_token(data={"sub": user.id}),
            "refresh_token": create_refresh_token(data={"sub": user.id}),
            "token_type": "bearer",
        }


    @router.get("/me", response_model=UserResponse)
    def get_current_user_profile(user: User = Depends(get_current_user)):
        return user
