"""Authentication utilities for the web application."""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass

from jose import jwt, JWTError


# Configuration
SECRET_KEY = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))


@dataclass
class TokenData:
    """Data extracted from a valid JWT token."""

    account_id: str
    character_id: Optional[str] = None
    is_admin: bool = False
    expires_at: Optional[datetime] = None


def create_access_token(
    account_id: str,
    character_id: Optional[str] = None,
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        account_id: The account ID (required)
        character_id: Optional character ID if playing
        is_admin: Whether the account has admin privileges
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    expire = datetime.utcnow() + expires_delta

    payload = {
        "sub": account_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "admin": is_admin,
    }

    if character_id:
        payload["char"] = character_id

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[TokenData]:
    """
    Verify and decode a JWT token.

    Args:
        token: The JWT token string

    Returns:
        TokenData if valid, None if invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        account_id = payload.get("sub")
        if not account_id:
            return None

        return TokenData(
            account_id=account_id,
            character_id=payload.get("char"),
            is_admin=payload.get("admin", False),
            expires_at=datetime.fromtimestamp(payload.get("exp", 0)),
        )

    except JWTError:
        return None


def refresh_token(
    token: str,
    new_character_id: Optional[str] = None,
) -> Optional[str]:
    """
    Refresh a token, optionally updating the character.

    Used when selecting a different character to play.

    Args:
        token: The existing valid token
        new_character_id: New character ID to set

    Returns:
        New token string if original was valid, None otherwise
    """
    token_data = verify_token(token)
    if not token_data:
        return None

    return create_access_token(
        account_id=token_data.account_id,
        character_id=new_character_id,
        is_admin=token_data.is_admin,
    )


def get_token_from_cookie(cookies: Dict[str, str]) -> Optional[str]:
    """Extract the session token from cookies."""
    return cookies.get("session")


def is_token_expiring_soon(token: str, threshold_minutes: int = 60) -> bool:
    """
    Check if a token will expire within the threshold.

    Useful for proactive token refresh.
    """
    token_data = verify_token(token)
    if not token_data or not token_data.expires_at:
        return True

    threshold = timedelta(minutes=threshold_minutes)
    return datetime.utcnow() + threshold >= token_data.expires_at


# Password validation utilities

def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets minimum requirements.

    Returns (is_valid, error_message).
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if len(password) > 128:
        return False, "Password must be less than 128 characters"

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)

    if not (has_upper and has_lower and has_digit):
        return False, "Password must contain uppercase, lowercase, and a number"

    return True, ""


def validate_email(email: str) -> tuple[bool, str]:
    """
    Basic email validation.

    Returns (is_valid, error_message).
    """
    if not email or len(email) < 5:
        return False, "Email is required"

    if len(email) > 255:
        return False, "Email is too long"

    if "@" not in email or "." not in email:
        return False, "Invalid email format"

    # Basic structure check
    parts = email.split("@")
    if len(parts) != 2:
        return False, "Invalid email format"

    local, domain = parts
    if not local or not domain:
        return False, "Invalid email format"

    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        return False, "Invalid email domain"

    return True, ""


def validate_character_name(name: str) -> tuple[bool, str]:
    """
    Validate character name.

    Returns (is_valid, error_message).
    """
    if not name:
        return False, "Name is required"

    if len(name) < 3:
        return False, "Name must be at least 3 characters"

    if len(name) > 20:
        return False, "Name must be 20 characters or less"

    if not name[0].isalpha():
        return False, "Name must start with a letter"

    if not all(c.isalnum() or c in "'-" for c in name):
        return False, "Name can only contain letters, numbers, apostrophes, and hyphens"

    # Check for reserved/forbidden names
    forbidden = {
        "admin", "administrator", "moderator", "mod", "gm", "gamemaster",
        "system", "server", "root", "null", "undefined", "test",
    }
    if name.lower() in forbidden:
        return False, "That name is not allowed"

    return True, ""
