from datetime import date, timedelta
from django.utils import timezone
from pydantic import ValidationError as PydanticError
from rest_framework import serializers
from apps.accounts.models import User
from .models import AIOutput, Meeting, MeetingParticipant
from .services import progress as live_progress
from .services.ai import ActionItemSchema
from apps.projects.models import Project

def sync_participants(meeting, users):
    existing = {l.user_id: l for l in meeting.links.all()}
    wanted = {u.id for u in users}
    meeting.links.exclude(user_id__in=wanted).delete()
    n = max([int(l.pseudonym[1:]) for l in existing.values()] + [0])
    for u in users:
        if u.id not in existing:
            n += 1
            MeetingParticipant.objects.create(meeting=meeting, user=u, pseudonym=f"P{n}")


class MeetingSerializer(serializers.ModelSerializer):
    participant_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, queryset=User.objects.filter(role="EMPLOYEE", is_active=True))
    participants = serializers.SerializerMethodField()
    manager_name = serializers.CharField(source="manager.display_name", read_only=True)
    has_audio = serializers.SerializerMethodField()
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all(), required=False, allow_null=True)
    project_name = serializers.CharField(source="project.name", default=None, read_only=True)
    progress = serializers.SerializerMethodField()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        now = timezone.now()
        minimum = now + timedelta(hours=1)

        if self.instance is not None:
            if self.instance.status != Meeting.Status.SCHEDULED:
                raise serializers.ValidationError("Only scheduled meetings can be edited.")
            if "meeting_mode" in attrs and attrs["meeting_mode"] != self.instance.meeting_mode:
                raise serializers.ValidationError("Meeting mode cannot be changed.")
            if "scheduled_at" in attrs and attrs["scheduled_at"] != self.instance.scheduled_at:
                if self.instance.scheduled_at <= minimum:
                    raise serializers.ValidationError({"scheduled_at": "Rescheduling closes one hour before the original meeting time. You may cancel instead."})
                if attrs["scheduled_at"] < minimum:
                    raise serializers.ValidationError({"scheduled_at": "Choose a new time at least one hour from now."})
        else:
            mode = attrs.get("meeting_mode", Meeting.Mode.NOW)
            when = attrs.get("scheduled_at")
            if mode == Meeting.Mode.NOW:
                attrs["scheduled_at"] = now
            elif not when:
                raise serializers.ValidationError({"scheduled_at": "Date and time are required."})
            elif mode == Meeting.Mode.LATER and when < minimum:
                raise serializers.ValidationError({"scheduled_at": "Scheduled meetings need at least one hour of advance notice."})
            elif mode == Meeting.Mode.PAST and when >= now:
                raise serializers.ValidationError({"scheduled_at": "Historical meetings must be in the past."})
            if mode == Meeting.Mode.LATER and not attrs.get("location", "").strip():
                raise serializers.ValidationError({"location": "Enter a location for the scheduled meeting."})
        return attrs

    def get_progress(self, m):
        return live_progress.get(m.id) if m.status == "PROCESSING" else None

    def validate_project(self, p):
        if p and p.manager_id != self.context["request"].user.id:
            raise serializers.ValidationError("Choose one of your own projects.")
        return p
    
    class Meta:
        model = Meeting
        fields = ["id", "title", "description", "scheduled_at", "meeting_mode", "location", "started_at", "is_confidential", "project", "project_name","status",
                  "processing_error", "processing_cancel_requested", "manager_name", "participant_ids", "participants",
                  "has_audio", "created_at", "progress"]
        read_only_fields = ["status", "processing_error", "processing_cancel_requested", "started_at"]

    def get_participants(self, m):
        is_manager = self.context["request"].user.role == "MANAGER"
        out = []
        for l in m.links.select_related("user"):
            d = {"id": l.user_id, "name": l.user.display_name}
            if is_manager:
                d["pseudonym"] = l.pseudonym  # identity mapping is manager-only
            out.append(d)
        return out

    def get_has_audio(self, m):
        return bool(m.audio)

    def create(self, v):
        users = v.pop("participant_ids", [])
        mode = v.get("meeting_mode", Meeting.Mode.NOW)
        v["status"] = Meeting.Status.SCHEDULED if mode == Meeting.Mode.LATER else Meeting.Status.DRAFT
        m = Meeting.objects.create(manager=self.context["request"].user, **v)
        sync_participants(m, users)
        return m

    def update(self, inst, v):
        users = v.pop("participant_ids", None)
        for k, val in v.items():
            setattr(inst, k, val)
        inst.save()
        if users is not None:
            sync_participants(inst, users)
        return inst


class OutputSerializer(serializers.ModelSerializer):
    action_items = serializers.ListField(child=serializers.DictField())

    class Meta:
        model = AIOutput
        fields = ["id", "meeting", "version", "status", "summary", "mom", "discussion_points",
                  "decisions", "action_items", "generated_by", "model_name", "created_at"]
        read_only_fields = ["meeting", "version", "status", "generated_by", "model_name"]

   
    def validate_action_items(self, items):
        valid = set(self.instance.meeting.links.values_list("user_id", flat=True))
        out = []
        for i, it in enumerate(items, 1):
            try:
                base = ActionItemSchema(
                    **{k: it[k] for k in ActionItemSchema.model_fields if k in it}).model_dump()
            except PydanticError:
                raise serializers.ValidationError(f"Action item {i} is invalid.")
            base["deadline"] = base["deadline"] or None
            if base["deadline"]:
                try:
                    date.fromisoformat(base["deadline"])
                except ValueError:
                    raise serializers.ValidationError(f"Action item {i}: deadline must be YYYY-MM-DD.")
            aid = it.get("assignee_id")
            try:
                aid = int(aid) if aid not in (None, "") else None
            except (TypeError, ValueError):
                raise serializers.ValidationError(f"Action item {i}: invalid assignee.")
            if aid is not None and aid not in valid:
                raise serializers.ValidationError(f"Action item {i}: assignee must be a meeting participant.")
            base.update(assignee_id=aid, discard=bool(it.get("discard", False)),
                        proof_required=bool(it.get("proof_required", False)))
            base["needs_review"] = aid is None or not base["deadline"] or base["confidence"] == "LOW"
            out.append(base)
        return out
    
    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Get participants linked to this meeting.
        participants = {
            link.user_id: link.user
            for link in instance.meeting.links.select_related("user")
        }

        # Add employee names to the API response.
        for item in data.get("action_items", []):
            assignee_id = item.get("assignee_id")

            try:
                assignee_id = (
                    int(assignee_id)
                    if assignee_id not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                assignee_id = None

            user = participants.get(assignee_id)

            if user:
                item["assignee_name"] = (
                    user.get_full_name().strip()
                    or user.username
                )
            else:
                item["assignee_name"] = None

        return data
