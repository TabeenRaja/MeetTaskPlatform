from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.services import notify
from apps.tasks.models import Task


class Command(BaseCommand):
    help = "Send due-soon and overdue reminders. Run daily. Duplicates are prevented by dedupe_key."

    def handle(self, *a, **o):
        today = timezone.localdate()
        qs = (Task.objects.filter(status__in=["PENDING", "IN_PROGRESS"], deadline__isnull=False)
              .select_related("assignee", "meeting__manager", "project__manager"))
        for t in qs.filter(deadline__lte=today + timedelta(days=1), deadline__gte=today):
            notify(t.assignee, "DEADLINE_SOON", f"Due soon: {t.title}", f"Deadline {t.deadline}",
                   f"/tasks/{t.id}", dedupe_key=f"soon-{t.id}-{t.deadline}")
        for t in qs.filter(deadline__lt=today):
            notify(t.assignee, "OVERDUE", f"Overdue: {t.title}", f"Was due {t.deadline}",
                   f"/tasks/{t.id}", dedupe_key=f"overdue-{t.id}-{today}")
            notify(t.owner, "OVERDUE", f"Overdue: {t.title}",
                   f"Assignee: {t.assignee.display_name}", f"/tasks/{t.id}",
                   dedupe_key=f"overdue-mgr-{t.id}-{today}")
        self.stdout.write("Reminders processed.")