"""
Authentication and RBAC Dependency for Enterprise Reverse-Proxy ADSSO.
Extracts user identity and role from forwarded reverse-proxy headers:
- X-User-Id
- X-Department-Id
- X-User-Role
- X-User-Name
"""

import re
from typing import Optional
from dataclasses import dataclass
from fastapi import Header, HTTPException, status, Depends
from config import settings

SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


@dataclass
class AuthContext:
    user_id: str
    department_id: str
    role: str
    full_name: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        """Check if user holds administrative privileges."""
        return self.role.lower() in ("admin", "administrator", "superuser")


def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_department_id: Optional[str] = Header(None, alias="X-Department-Id"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name"),
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> AuthContext:
    """
    Extracts authenticated user context from reverse-proxy ADSSO headers.
    Falls back to safe default values when running standalone.
    Validates X-Internal-Secret against settings.proxy_secret_key when configured.
    """
    # Verify reverse proxy secret if configured
    if getattr(settings, "proxy_secret_key", None):
        if x_internal_secret != settings.proxy_secret_key:
            if x_user_role and x_user_role.lower() in ("admin", "administrator", "superuser", "analyst"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Xác thực Reverse Proxy thất bại (thiếu hoặc sai X-Internal-Secret)."
                )
            x_user_id = "anonymous_user"
            x_department_id = "GENERAL"
            x_user_role = "user"
            x_user_name = None

    user_id = (x_user_id or "anonymous_user").strip()
    department_id = (x_department_id or "GENERAL").strip()
    role = (x_user_role or "user").strip()
    full_name = x_user_name.strip() if x_user_name else None

    if not SAFE_ID_PATTERN.match(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã định danh người dùng (User ID) chứa ký tự không hợp lệ."
        )

    if not SAFE_ID_PATTERN.match(department_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã phòng ban (Department ID) chứa ký tự không hợp lệ."
        )

    if not re.match(r"^[a-zA-Z0-9_-]{1,32}$", role):
        role = "user"

    return AuthContext(
        user_id=user_id,
        department_id=department_id,
        role=role,
        full_name=full_name
    )


def require_admin(
    auth: AuthContext = Depends(get_current_user)
) -> AuthContext:
    """Dependency that ensures the authenticated user is an administrator."""
    if not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Truy cập bị từ chối: Yêu cầu quyền quản trị viên (Admin)."
        )
    return auth
