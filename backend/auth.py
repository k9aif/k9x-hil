import hmac
import os
import time
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User

SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable must be set (see .env.sample)"
    )
ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 hours


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _api_key_user(api_key: Optional[str], db: Session) -> Optional[User]:
    """1.5.0: a server-to-server caller (e.g. the openai.k9x.ai demo's backend) may send X-API-Key instead of a
    sign-in token. It must match HIL_API_KEY and acts as the user HIL_API_KEY_USER (by email): that user's role
    still decides what may be approved, and every decision is recorded under that user. Unset: no API key accepted."""
    expected = os.environ.get("HIL_API_KEY", "")
    if not api_key or not expected:
        return None
    if not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")
    email = os.environ.get("HIL_API_KEY_USER", "")
    user = db.query(User).filter(User.email == email).first() if email else None
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="API key user not found or inactive")
    return user


def get_current_user(
    authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    key_user = _api_key_user(x_api_key, db)
    if key_user is not None:
        return key_user
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization[len("Bearer ") :]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user
