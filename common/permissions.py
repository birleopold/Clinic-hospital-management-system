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
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'is_superuser', False):
            return True
        # Resolve role map
        role_map = self._get_role_map(view)
        # Allow read for all authenticated staff by default unless role_map specifies restrictions
        if request.method in SAFE_METHODS and not (role_map and (role_map.get('GET') or role_map.get('any'))):
            return True
        if not role_map:
            return True  # fallback to default IsAuthenticated
        # Prefer action over method if present
        action = getattr(view, 'action', None)
        required_roles: Optional[List[str]] = None
        if action and action in role_map:
            required_roles = role_map.get(action)
        if not required_roles:
            required_roles = role_map.get(request.method)
        if not required_roles:
            required_roles = role_map.get('any')
        if not required_roles:
            # No restriction specified; allow
            return True
        return getattr(user, 'role', None) in required_roles

    def has_object_permission(self, request, view, obj) -> bool:
        # Defer to has_permission for simplicity in MVP
        return self.has_permission(request, view)

    @staticmethod
    def _get_role_map(view) -> Optional[Dict[str, List[str]]]:
        role_map = getattr(view, 'role_map', None)
        if callable(role_map):
            return role_map()
        return role_map
