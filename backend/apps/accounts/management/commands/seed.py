import os
from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create initial admin from env vars. Use --demo for sample manager/employees."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true")

    def handle(self, *a, **o):
        u, p = os.getenv("ADMIN_USERNAME"), os.getenv("ADMIN_PASSWORD")
        if not u or not p:
            raise CommandError("Set ADMIN_USERNAME and ADMIN_PASSWORD in .env")
        if not User.objects.filter(username=u).exists():
            User.objects.create_user(u, os.getenv("ADMIN_EMAIL", ""), p, role="ADMIN", is_staff=True)
            self.stdout.write(f"Admin '{u}' created")
        if o["demo"]:
            demo = [("manager1", "Mona", "Raza", "MANAGER"),
                    ("ali", "Ali", "Khan", "EMPLOYEE"),
                    ("sara", "Sara", "Ahmed", "EMPLOYEE")]
            for un, f, l, r in demo:
                if not User.objects.filter(username=un).exists():
                    User.objects.create_user(un, f"{un}@example.com", "demo12345",
                                             first_name=f, last_name=l, role=r)
            self.stdout.write("Demo users created (password: demo12345)")