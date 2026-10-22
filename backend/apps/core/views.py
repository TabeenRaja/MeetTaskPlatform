from datetime import timedelta
from django.db.models import Count
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.meetings.models import Meeting
from apps.tasks.models import Task
from .models import AuditLog, Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "message", "link", "is_read", "email_status", "created_at"]


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        self.get_queryset().update(is_read=True)
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        self.get_queryset().filter(pk=pk).update(is_read=True)
        return Response({"ok": True})


class AuditSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", default=None, read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "actor_name", "action", "target_type", "target_id", "detail", "created_at"]


class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditSerializer
    permission_classes = [IsAdmin]
    queryset = AuditLog.objects.select_related("actor")


class DashboardView(APIView):
    def get(self, request):
        u, today = request.user, timezone.localdate()
        active = ["PENDING", "IN_PROGRESS"]
        if u.role == "MANAGER":
            t = Task.objects.for_manager(u)
            m = Meeting.objects.filter(manager=u)
            return Response({
                "total_meetings": m.count(),
                "awaiting_review": m.filter(status="PENDING_REVIEW").count(),
                "approved_meetings": m.filter(status="APPROVED").count(),
                "active_tasks": t.filter(status__in=active + ["IN_REVIEW"]).count(),
                "proofs_awaiting": t.filter(status="IN_REVIEW").count(),
                "completed_tasks": t.filter(status="DONE").count(),
                "overdue_tasks": t.filter(status__in=active, deadline__lt=today).count(),
            })
        if u.role == "EMPLOYEE":
            t = Task.objects.filter(assignee=u)
            return Response({
                "assigned_tasks": t.count(),
                "upcoming_deadlines": t.filter(status__in=active, deadline__gte=today,
                                               deadline__lte=today + timedelta(days=7)).count(),
                "in_progress": t.filter(status="IN_PROGRESS").count(),
                "in_review": t.filter(status="IN_REVIEW").count(),
                "completed_tasks": t.filter(status="DONE").count(),
                "overdue_tasks": t.filter(status__in=active, deadline__lt=today).count(),
            })
        if u.role == "ADMIN":
            return Response({
                "users": dict(User.objects.order_by().values_list("role").annotate(c=Count("id"))),
                "active_users": User.objects.filter(is_active=True).count(),
                "meetings": dict(Meeting.objects.order_by().values_list("status").annotate(c=Count("id"))),
                "tasks": dict(Task.objects.order_by().values_list("status").annotate(c=Count("id"))),
                "recent_audit": AuditSerializer(AuditLog.objects.select_related("actor")[:10], many=True).data,
            })
        return Response({})