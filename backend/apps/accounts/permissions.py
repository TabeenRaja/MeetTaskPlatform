from rest_framework.permissions import BasePermission


def role_required(*roles):
    class RolePermission(BasePermission):
        def has_permission(self, request, view):
            u = request.user
            return bool(u and u.is_authenticated and u.is_active and u.role in roles)
    return RolePermission


IsAdmin = role_required("ADMIN")
IsManager = role_required("MANAGER")
IsMember = role_required("MANAGER", "EMPLOYEE")


def HasPerm(code, message=None):
    """DRF permission class: the user must hold this permission (via their role or a personal override).

        permission_classes = [HasPerm("projects.manage")]
    """

    class PermissionCodePermission(BasePermission):
        def has_permission(self, request, view):
            u = request.user
            return bool(u and u.is_authenticated and u.is_active and u.has_access(code))

    PermissionCodePermission.message = message or "You do not have permission to do this."
    PermissionCodePermission.__name__ = f"HasPerm_{code.replace('.', '_')}"
    return PermissionCodePermission


# Managers by default; admins decide per role and per person (employees included).
CanCreateMeetings = HasPerm("meetings.create", "You do not have permission to create meetings.")
