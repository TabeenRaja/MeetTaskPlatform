import os
import logging
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.accounts.permissions import CanCreateMeetings, HasPerm, IsManager
from apps.core.services import audit
from .models import AIOutput, Meeting
from .serializers import MeetingSerializer, OutputSerializer
from .services import approval, pipeline


logger = logging.getLogger(__name__)


def notify_participants(meeting, subject, verb, extra_recipients=None):
    """Attempt invitation delivery; never report success if sending fails.
    Uses existing account email addresses and Django EMAIL_* settings.
    Returns a count of accepted email messages (not guaranteed inbox delivery).
    """
    recipients = sorted({u.email for u in meeting.participants.all() if u.email} | set(extra_recipients or []))
    if not recipients:
        return {"notification_status": "no_email_addresses", "notifications_sent": 0}
    when = timezone.localtime(meeting.scheduled_at).strftime("%d %b %Y at %I:%M %p %Z")
    body = (f"{verb}: {meeting.title}\n"
            f"Date/time: {when}\nLocation: {meeting.location or 'To be confirmed'}\n"
            f"Agenda: {meeting.description or 'Not provided'}\n\n"
            + ("This meeting has been cancelled. Please do not attend." if meeting.status == Meeting.Status.CANCELLED else "Please attend at the scheduled location."))
    try:
        # Single email per participant avoids exposing recipient addresses to others.
        sent = sum(send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [addr], fail_silently=False)
                   for addr in recipients)
        return {"notification_status": "sent" if sent == len(recipients) else "partial",
                "notifications_sent": sent, "notifications_expected": len(recipients)}
    except Exception:
        logger.exception("Meeting %s invitation email delivery failed", meeting.pk)
        return {"notification_status": "failed", "notifications_sent": 0}


class MeetingViewSet(viewsets.ModelViewSet):
    serializer_class = MeetingSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]  # no delete

    def get_permissions(self):
        # Creating needs the "Create meetings" permission (managers have it by default; an admin can
        # grant it to a role or a single employee). Whoever created a meeting runs it.
        if self.action == "create":
            return [CanCreateMeetings()]
        if self.action in ("update", "partial_update", "upload_audio", "cancel_processing", "start", "cancel"):
            return [(IsManager | CanCreateMeetings)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        u, qs = self.request.user, Meeting.objects.all()
        if u.role == "ADMIN":
            return Meeting.objects.none()
        # meetings you created, plus meetings you were invited to
        qs = qs.filter(Q(manager=u) | Q(participants=u))
        q, st = self.request.query_params.get("q"), self.request.query_params.get("status")
        if q:
            qs = qs.filter(title__icontains=q)
        if st:
            qs = qs.filter(status=st)
        return qs.distinct()

    def perform_create(self, s):
        m = s.save()
        audit(self.request.user, "MEETING_CREATED", m)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if response.data.get("status") == Meeting.Status.SCHEDULED:
            m = self.get_queryset().get(pk=response.data["id"])
            response.data.update(notify_participants(m, f"Meeting invitation: {m.title}", "Meeting scheduled"))
        return response

    def perform_update(self, serializer):
        instance = serializer.save()
        audit(self.request.user, "MEETING_UPDATED", instance)

    def update(self, request, *args, **kwargs):
        # Serialize concurrent editing/starting/cancellation of the same meeting.
        with transaction.atomic():
            meeting = Meeting.objects.select_for_update().get(pk=self.get_object().pk)
            previous_emails = {u.email for u in meeting.participants.all() if u.email}
            serializer = self.get_serializer(meeting, data=request.data, partial=kwargs.get("partial", False))
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            data = dict(serializer.data)
        if meeting.status == Meeting.Status.SCHEDULED:
            data.update(notify_participants(meeting, f"Meeting updated: {meeting.title}", "Meeting details updated", previous_emails))
        return Response(data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        # A scheduled meeting may start on time or late, never early.
        with transaction.atomic():
            m = Meeting.objects.select_for_update().get(pk=pk, manager=request.user)
            if m.status != Meeting.Status.SCHEDULED:
                raise ValidationError("Only scheduled meetings can be started.")
            if timezone.now() < m.scheduled_at:
                raise ValidationError("This meeting cannot start before its scheduled time. Reschedule it with one hour notice if needed.")
            m.status = Meeting.Status.IN_PROGRESS
            m.started_at = timezone.now()
            m.save(update_fields=["status", "started_at"])
        audit(request.user, "MEETING_STARTED", m)
        return Response(self.get_serializer(m).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            m = Meeting.objects.select_for_update().get(pk=pk, manager=request.user)
            if m.status != Meeting.Status.SCHEDULED:
                raise ValidationError("Only meetings that have not started can be cancelled.")
            m.status = Meeting.Status.CANCELLED
            m.save(update_fields=["status"])
        audit(request.user, "MEETING_CANCELLED", m)
        result = notify_participants(m, f"Meeting cancelled: {m.title}", "Meeting cancelled")
        return Response({**self.get_serializer(m).data, **result})

    @action(detail=True, methods=["post"], url_path="upload-audio")
    def upload_audio(self, request, pk=None):
        m = self.get_object()
        f = request.FILES.get("audio")
        if not f:
            raise ValidationError("No audio file provided (field name: 'audio').")
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in settings.ALLOWED_AUDIO_EXT:
            raise ValidationError(f"Unsupported format. Allowed: {', '.join(sorted(settings.ALLOWED_AUDIO_EXT))}")
        if f.size > settings.MAX_AUDIO_MB * 1024 * 1024:
            raise ValidationError(f"File too large. Max {settings.MAX_AUDIO_MB} MB.")
        if m.status == "SCHEDULED":
            raise ValidationError("Start the scheduled meeting before uploading audio.")
        if m.status == "CANCELLED":
            raise ValidationError("Cancelled meetings cannot accept recordings.")
        if m.processing_cancel_requested:
            raise ValidationError("The previous processing run is being cleaned up. Please retry once cancellation finishes.")
        if m.status == "PROCESSING":
            raise ValidationError("Already processing.")
        if m.status == "APPROVED":
            raise ValidationError("Approved meetings cannot be reprocessed.")
        if not m.links.exists():
            raise ValidationError("Add at least one participant first.")
        m.audio.save(f"meeting_{m.id}{ext}", f)
        m.status = "PROCESSING"
        m.processing_cancel_requested = False
        m.processing_error = ""
        m.save(update_fields=["status", "processing_cancel_requested", "processing_error"])
        audit(request.user, "AUDIO_UPLOADED", m, size=f.size)
        pipeline.start(m.id)
        return Response({"status": "PROCESSING"}, status=202)

    @action(detail=True, methods=["post"], url_path="cancel-processing")
    def cancel_processing(self, request, pk=None):
        # Cooperative cancel. Existing blocking Whisper/Gemini calls cannot be force-killed.
        # The worker checks this flag after every stage and before publishing results.
        with transaction.atomic():
            m = Meeting.objects.select_for_update().get(pk=pk, manager=request.user)
            if m.status != Meeting.Status.PROCESSING:
                raise ValidationError("This meeting is not currently processing.")
            # The meeting stops showing PROCESSING immediately. Keep the cancellation
            # flag set until the background worker has safely released its old audio.
            # Uploading again is blocked while that cleanup remains outstanding.
            m.processing_cancel_requested = True
            m.status = Meeting.Status.DRAFT
            m.processing_error = ""
            m.save(update_fields=["processing_cancel_requested", "status", "processing_error"])
        audit(request.user, "PROCESSING_CANCEL_REQUESTED", m)
        return Response({"status": "DRAFT", "processing_cancel_requested": True,
                         "message": "Processing cancelled for this meeting. Background cleanup may still be pending."})

    @action(detail=True, methods=["get"])
    def transcript(self, request, pk=None):
        m = self.get_object()
        t = getattr(m, "transcript", None)
        if not t:
            return Response({"available": False})
        u = request.user
        if m.manager_id == u.id:
            audit(u, "TRANSCRIPT_VIEWED", m)
            return Response({"available": True, "source": t.source,
                             "original": t.original_text, "sanitized": t.sanitized_text})
        if m.is_confidential:
            raise PermissionDenied("Transcript of a confidential meeting is restricted to the manager.")
        return Response({"available": True, "source": t.source, "sanitized": t.sanitized_text})

    @action(detail=True, methods=["get"])
    def output(self, request, pk=None):
        m = self.get_object()
        qs = m.outputs.all()
        if m.manager_id != request.user.id:
            qs = qs.filter(status="APPROVED")
        o = qs.first()
        return Response(OutputSerializer(o).data if o else None)


class OutputViewSet(viewsets.GenericViewSet):
    serializer_class = OutputSerializer
    permission_classes = [HasPerm("meetings.review")]

    def get_queryset(self):
        return AIOutput.objects.filter(meeting__manager=self.request.user)

    def partial_update(self, request, pk=None):
        o = self.get_object()
        if o.status != "PENDING_REVIEW":
            raise ValidationError("Only outputs pending review can be edited.")
        s = self.get_serializer(o, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit(request.user, "OUTPUT_EDITED", o, fields=list(s.validated_data.keys()))
        return Response(s.data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        o = self.get_object()
        out, created = approval.approve(o.pk, request.user)
        return Response({"status": out.status, "tasks_created": created})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        o = self.get_object()
        approval.reject(o.pk, request.user, request.data.get("reason", ""))
        return Response({"status": "REJECTED"})

    @action(detail=True, methods=["post"])
    def resubmit(self, request, pk=None):
        o = self.get_object()
        approval.resubmit(o.pk, request.user)
        return Response({"status": "PENDING_REVIEW"})