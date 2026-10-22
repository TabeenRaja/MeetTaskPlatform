from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.core.services import audit, notify
from apps.tasks.models import Task, TaskEvent
from ..models import AIOutput, Review


@transaction.atomic
def approve(output_id, reviewer):
    """Idempotent. Tasks only exist after this succeeds."""
    out = AIOutput.objects.select_for_update().select_related("meeting").get(pk=output_id)
    if out.status == "APPROVED":
        return out, False  # retry: no duplicates
    if out.status != "PENDING_REVIEW":
        raise ValidationError("Only outputs pending review can be approved.")
    valid_ids = set(out.meeting.links.values_list("user_id", flat=True))
    now, created = timezone.now(), []
    for i, it in enumerate(out.action_items):
        if it.get("discard"):
            continue
        if it.get("assignee_id") not in valid_ids:
            raise ValidationError(f"Action item {i + 1} needs a valid assignee (or mark it discarded).")
        task, was_new = Task.objects.get_or_create(
            ai_output=out, source_index=i,
            defaults=dict(meeting=out.meeting, project=out.meeting.project, title=it["title"], description=it.get("description", ""),
                          assignee_id=it["assignee_id"], deadline=it.get("deadline") or None,
                          priority=it.get("priority", "MEDIUM"), approved_by=reviewer, approved_at=now))
        if was_new:
            TaskEvent.objects.create(task=task, actor=reviewer, description="Task created on approval")
            created.append(task)
    out.status = "APPROVED"
    out.save(update_fields=["status"])
    out.meeting.status = "APPROVED"
    out.meeting.save(update_fields=["status"])
    Review.objects.create(output=out, reviewer=reviewer, decision="APPROVED")
    audit(reviewer, "OUTPUT_APPROVED", out, tasks_created=len(created))
    for t in created:
        notify(t.assignee, "TASK_ASSIGNED", f"New task: {t.title}",
               f"Deadline: {t.deadline or 'none'}", f"/tasks/{t.id}", dedupe_key=f"assigned-{t.id}")
    return out, True


@transaction.atomic
def reject(output_id, reviewer, reason):
    out = AIOutput.objects.select_for_update().select_related("meeting").get(pk=output_id)
    if out.status != "PENDING_REVIEW":
        raise ValidationError("Only outputs pending review can be rejected.")
    if not reason.strip():
        raise ValidationError("A rejection reason is required.")
    out.status = "REJECTED"
    out.save(update_fields=["status"])
    out.meeting.status = "REJECTED"
    out.meeting.save(update_fields=["status"])
    Review.objects.create(output=out, reviewer=reviewer, decision="REJECTED", reason=reason)
    audit(reviewer, "OUTPUT_REJECTED", out, reason=reason)
    return out


@transaction.atomic
def resubmit(output_id, reviewer):
    out = AIOutput.objects.select_for_update().select_related("meeting").get(pk=output_id)
    if out.status != "REJECTED":
        raise ValidationError("Only rejected outputs can be resubmitted.")
    out.status = "PENDING_REVIEW"
    out.save(update_fields=["status"])
    out.meeting.status = "PENDING_REVIEW"
    out.meeting.save(update_fields=["status"])
    audit(reviewer, "OUTPUT_RESUBMITTED", out)
    return out