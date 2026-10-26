from django.contrib.auth.models import AbstractUser
from django.db import models

from .access import ALL_CODES, DEFAULT_ROLE_PERMISSIONS


class Role(models.Model):
    """A named set of permissions an admin can create and assign to users.

    `base` is the access level the rest of the app already checks (ADMIN / MANAGER / EMPLOYEE),
    so existing views keep working. `permissions` fine-tunes what the role may do.
    """

    class Base(models.TextChoices):
        ADMIN = "ADMIN"
        MANAGER = "MANAGER"
        EMPLOYEE = "EMPLOYEE"

    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    base = models.CharField(max_length=10, choices=Base.choices, default=Base.EMPLOYEE)
    permissions = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN"
        MANAGER = "MANAGER"
        EMPLOYEE = "EMPLOYEE"

    # `role` is the base access level and is kept in sync with role_ref.base, so every
    # existing `user.role == "MANAGER"` check keeps working with custom roles.
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.EMPLOYEE, db_index=True)
    role_ref = models.ForeignKey(
        "accounts.Role", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    # Per-person exceptions to the role: {"meetings.create": true, "tasks.assign": false}
    permission_overrides = models.JSONField(default=dict, blank=True)
    department = models.CharField(max_length=100, blank=True, default="")
    job_title = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    must_change_password = models.BooleanField(default=False)
    # Legacy admin override for creating meetings. Still honoured; new edits use permission_overrides.
    meeting_create_override = models.BooleanField(null=True, blank=True, default=None)

    def save(self, *args, **kwargs):
        # Make sure every user points at a Role row (the matching built-in one by default).
        if self.role_ref_id is None and kwargs.get("update_fields") is None:
            self.role_ref = Role.objects.filter(base=self.role).order_by("-is_system", "id").first()
        super().save(*args, **kwargs)

    # ---- permissions -------------------------------------------------------------------
    def all_overrides(self):
        """Per-user overrides, including the legacy meeting override."""
        ov = dict(self.permission_overrides or {})
        if "meetings.create" not in ov and self.meeting_create_override is not None:
            ov["meetings.create"] = self.meeting_create_override
        return ov

    def permission_set(self):
        """Everything this user may do: role permissions, then per-user allow/deny overrides."""
        if self.role == self.Role.ADMIN:
            return set(ALL_CODES)
        base = self.role_ref.permissions if self.role_ref_id else DEFAULT_ROLE_PERMISSIONS.get(self.role, [])
        perms = {c for c in base if c in ALL_CODES}
        for code, allowed in self.all_overrides().items():
            if code not in ALL_CODES:
                continue
            if allowed:
                perms.add(code)
            else:
                perms.discard(code)
        return perms

    def set_override(self, code, allowed):
        self.permission_overrides = {**(self.permission_overrides or {}), code: bool(allowed)}
        if code == "meetings.create":
            self.meeting_create_override = None

    def clear_override(self, code):
        self.permission_overrides = {k: v for k, v in (self.permission_overrides or {}).items() if k != code}
        if code == "meetings.create":
            self.meeting_create_override = None

    def has_access(self, code):
        return code in self.permission_set()

    @property
    def role_name(self):
        return self.role_ref.name if self.role_ref_id else self.role.title()

    @property
    def can_create_meetings(self):
        return self.has_access("meetings.create")

    @can_create_meetings.setter
    def can_create_meetings(self, value):
        self.permission_overrides = {**(self.permission_overrides or {}), "meetings.create": bool(value)}
        self.meeting_create_override = None

    @property
    def display_name(self):
        return self.get_full_name() or self.username
