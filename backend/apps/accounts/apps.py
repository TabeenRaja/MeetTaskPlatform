from django.apps import AppConfig
from django.db.utils import OperationalError, ProgrammingError
from django.db.models.signals import post_migrate


def seed_roles(sender, apps=None, **kwargs):
    """Create the built-in Admin / Manager / Employee roles and attach existing users to them.

    Safe to run on every migrate: existing roles (and any permissions an admin edited) are left alone.
    """
    from .access import SYSTEM_ROLES

    try:
        Role = apps.get_model("accounts", "Role")
        User = apps.get_model("accounts", "User")
        spec_by_base = {r["base"]: r for r in SYSTEM_ROLES}
        # Admin is always present and locked.
        admin_spec = spec_by_base["ADMIN"]
        admin, _ = Role.objects.get_or_create(
            is_system=True, base="ADMIN",
            defaults={"name": admin_spec["name"], "description": admin_spec["description"],
                      "permissions": admin_spec["permissions"]},
        )
        # Manager / Employee are created once, as normal roles the admin can rename or delete.
        if not Role.objects.exclude(base="ADMIN").exists():
            for base in ("MANAGER", "EMPLOYEE"):
                spec = spec_by_base[base]
                Role.objects.create(name=spec["name"], base=base, description=spec["description"],
                                    permissions=spec["permissions"], is_system=False)
        # Attach any user without a role to the first role of the matching level.
        for base in ("ADMIN", "MANAGER", "EMPLOYEE"):
            role = Role.objects.filter(base=base).order_by("-is_system", "id").first()
            if role:
                User.objects.filter(role_ref__isnull=True, role=base).update(role_ref=role)
    except (LookupError, OperationalError, ProgrammingError):
        # accounts migrations not applied yet
        return


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        post_migrate.connect(seed_roles, sender=self)
