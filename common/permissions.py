from typing import Dict, List, Optional
from rest_framework.permissions import BasePermission, SAFE_METHODS


class RolePermission(BasePermission):
    """
    Enforce role-based access per action or HTTP method.
    Views should define `role_map` as either a dict or a callable returning a dict.
    Keys can be DRF actions (e.g., 'list', 'retrieve', 'create', 'update', 'partial_update', 'destroy')
    or HTTP methods (e.g., 'GET', 'POST', ...). A special key 'any' applies to all requests.
    """

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if getattr(user, 'is_superuser', False):
            return True
        # Resolve role map
        role_map = self._get_role_map(view)
        if not role_map:
            return True  # fallback to default IsAuthenticated
        # Resolve explicit rules before the read fallback. An empty rule denies access.
        action = getattr(view, 'action', None)
        method = 'GET' if request.method == 'HEAD' else request.method
        for key in (action, method, 'any'):
            if key in role_map:
                return getattr(user, 'role', None) in (role_map[key] or [])
        # Preserve authenticated read access; unspecified writes fail closed.
        return request.method in SAFE_METHODS

    def has_object_permission(self, request, view, obj) -> bool:
        # Defer to has_permission for simplicity in MVP
        return self.has_permission(request, view)

    @staticmethod
    def _get_role_map(view) -> Optional[Dict[str, List[str]]]:
        role_map = getattr(view, 'role_map', None)
        if callable(role_map):
            return role_map()
        return role_map
