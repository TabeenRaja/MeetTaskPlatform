# Roles & access: install steps

## 1. Backend (Django)

Copy these into `apps/accounts/` (replace the existing ones):
`access.py` (new), `models.py`, `permissions.py`, `serializers.py`, `views.py`, `urls.py`, `apps.py`

Then run:

    python manage.py makemigrations accounts
    python manage.py migrate

`migrate` also creates a locked Admin role plus Manager and Employee roles (ordinary roles you can rename or delete)
and attaches every existing user to the matching one. Nothing changes for current users: managers keep their access, and any old
"can create meetings" override is still honoured.

Make sure `INSTALLED_APPS` uses `"apps.accounts.apps.AccountsConfig"` (or that Django auto-detects it),
otherwise the seeding in `apps.py` will not run.

New API endpoints (all admin only):
- `GET/POST /roles/`, `GET/PATCH/DELETE /roles/<id>/`  (`?assignable=1` hides the Admin role)
- `GET /permissions/`  (the list of permissions shown in the editor)
- `/users/` now accepts `role_id` and `permission_overrides`, and returns `role_name`, `permissions`.

## 2. Frontend (React)

Copy into `src/`: `access.js`, `App.jsx`, `components/Layout.jsx`
and into `src/pages/`: `Roles.jsx`, `RoleForm.jsx`, `Userform.jsx`, `Users.jsx`, `Dashboard.jsx`

`App.jsx` has the `/roles` routes; `Layout.jsx` adds the "Roles" button under "Users" in the admin sidebar.

## 3. Making a permission actually do something

The role editor stores the choices. Each action is only restricted once its API view checks it.
Creating meetings is already wired up (the existing `CanCreateMeetings` now reads roles and overrides).

For the others, change the view's permission line, for example:

    from apps.accounts.permissions import HasPerm
    permission_classes = [HasPerm("projects.manage")]      # was IsManager

Codes available: `meetings.create`, `meetings.review`, `tasks.assign`, `tasks.review`,
`projects.manage`, `analytics.view`. To add a new one, add a line to `PERMISSIONS` in `access.py`.
In React, hide buttons with `can(user, "projects.manage")` from `access.js`.
