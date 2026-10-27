"""Workload warning: how busy each employee already is, so a manager can see it before assigning more work.

GET /api/workload/?ids=3,5,8   ->   {"limits": {...}, "people": {"3": {"open": 4, "overdue": 1, "due_soon": 2, "overloaded": false}, ...}}

Counts only (no task titles), so it leaks nothing a manager could not already see on the assignment screens.
"""
from datetime import timedelta
from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import HasPerm
from .models import Task

MAX_IDS = 200


def limits():
    return {"max_open": settings.WORKLOAD_MAX_OPEN, "max_overdue": settings.WORKLOAD_MAX_OVERDUE,
            "due_soon_days": settings.WORKLOAD_DUE_SOON_DAYS}


def is_overloaded(open_count, overdue_count):
    lim = limits()
    return open_count > lim["max_open"] or overdue_count > lim["max_overdue"]


class WorkloadView(APIView):
    permission_classes = [HasPerm("tasks.assign")]

    def get(self, request):
        ids = []
        for part in (request.query_params.get("ids") or "").split(","):
            part = part.strip()
            if part.isdigit() and int(part) not in ids:
                ids.append(int(part))
        ids = ids[:MAX_IDS]
        today = timezone.localdate()
        soon = today + timedelta(days=settings.WORKLOAD_DUE_SOON_DAYS)
        # Open = not Done. Overdue = past its deadline and still with the employee (a task waiting for the
        # manager's proof review is not the employee's delay, the same rule the Tasks page uses).
        rows = (Task.objects.filter(assignee_id__in=ids).exclude(status="DONE").values("assignee_id")
                .annotate(open=Count("id"),
                          overdue=Count("id", filter=Q(deadline__lt=today) & ~Q(status="IN_REVIEW")),
                          due_soon=Count("id", filter=Q(deadline__gte=today, deadline__lte=soon))))
        found = {r["assignee_id"]: r for r in rows}
        people = {}
        for i in ids:
            r = found.get(i, {})
            o, od, ds = r.get("open", 0), r.get("overdue", 0), r.get("due_soon", 0)
            people[str(i)] = {"open": o, "overdue": od, "due_soon": ds, "overloaded": is_overloaded(o, od)}
        return Response({"limits": limits(), "people": people})
