"""Permission catalogue and the built-in roles.

To make a new action controllable from the admin portal, add one entry to PERMISSIONS.
It then appears automatically in the role editor and on each user's access settings.
Enforce it in a view with:  permission_classes = [HasPerm("your.code")]
"""

PERMISSIONS = [
    {
        "code": "meetings.create",
        "group": "Meetings",
        "label": "Create meetings",
        "description": "Schedule and capture new meetings.",
    },
    {
        "code": "meetings.review",
        "group": "Meetings",
        "label": "Review & approve meetings",
        "description": "Approve or reject a meeting's outcomes before tasks start.",
    },
    {
        "code": "tasks.assign",
        "group": "Tasks",
        "label": "Create & assign tasks",
        "description": "Create tasks and assign them to employees.",
    },
    {
        "code": "tasks.review",
        "group": "Tasks",
        "label": "Review task proof",
        "description": "Accept or send back proof of completion submitted by employees.",
    },
    {
        "code": "projects.manage",
        "group": "Projects",
        "label": "Create & manage projects",
        "description": "Create projects and group meetings and backlog work under them.",
    },
    {
        "code": "analytics.view",
        "group": "Reports",
        "label": "View analytics",
        "description": "Open the weekly analytics reports.",
    },
]

ALL_CODES = [p["code"] for p in PERMISSIONS]

# Built-in roles. They are created automatically after `migrate` and cannot be deleted.
# "base" is the access level the rest of the app already understands (ADMIN / MANAGER / EMPLOYEE).
SYSTEM_ROLES = [
    {
        "name": "Admin",
        "base": "ADMIN",
        "description": "Full control of the workspace. Locked: cannot be edited or assigned.",
        "permissions": list(ALL_CODES),
    },
    {
        "name": "Manager",
        "base": "MANAGER",
        "description": "Runs meetings, reviews outcomes and manages team work.",
        "permissions": list(ALL_CODES),
    },
    {
        "name": "Employee",
        "base": "EMPLOYEE",
        "description": "Works on assigned tasks and joins meetings.",
        "permissions": [],
    },
]

# Permissions that belong to the manager workspace (review queue, task assignment, projects, analytics).
# A role holding any of them gets the manager screens automatically; otherwise it gets the employee screens.
MANAGER_PERMISSIONS = {"meetings.review", "tasks.assign", "tasks.review", "projects.manage", "analytics.view"}


def base_for(permissions):
    """The workspace (MANAGER or EMPLOYEE) a role gets, worked out from its permissions."""
    return "MANAGER" if MANAGER_PERMISSIONS & set(permissions or []) else "EMPLOYEE"


DEFAULT_ROLE_PERMISSIONS = {r["base"]: r["permissions"] for r in SYSTEM_ROLES}
