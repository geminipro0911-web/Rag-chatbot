"""
User Context Domain Entity for RBAC Enforcement.
"""

from pydantic import BaseModel, Field
from typing import Optional


class UserContext(BaseModel):
    user_id: str = Field(..., description="Unique user identifier")
    department_id: str = Field(..., description="User's primary department identifier")
    role: str = Field(default="user", description="User role: 'admin', 'analyst', 'user'")
    username: Optional[str] = Field(default=None)

    @property
    def is_admin(self) -> bool:
        return self.role.lower() == "admin"

    def can_access(self, target_department_id: str, is_public: bool, owner_user_id: str) -> bool:
        """
        Core RBAC rule:
        User can access document/table if:
        - User is admin, OR
        - department_id matches, OR
        - is_public is True, OR
        - owner_user_id is the user themself.
        """
        if self.is_admin:
            return True
        if is_public:
            return True
        if self.department_id == target_department_id:
            return True
        if self.user_id == owner_user_id:
            return True
        return False
