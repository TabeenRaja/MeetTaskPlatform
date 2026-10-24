import threading
from datetime import date
from django.db import close_old_connections, transaction
from apps.core.services import audit, notify
from ..models import AIOutput, Meeting, Transcript
from .ai import AIError, analyze
from .pii import match_participant, sanitize
from . import progress
from .transcription import get_transcriber


def start(meeting_id):
    progress.set_stage(meeting_id, "queued")
    threading.Thread(target=run, args=(meeting_id,), daemon=True).start()  # prototype; use Celery later


class ProcessingCancelled(Exception):
    pass


def check_not_cancelled(meeting_id):
    if Meeting.objects.filter(pk=meeting_id, processing_cancel_requested=True).exists():
        raise ProcessingCancelled()


def finish_cancelled(meeting_id):
    with transaction.atomic():
        m = Meeting.objects.select_for_update().get(pk=meeting_id)
        if m.processing_cancel_requested:
            # Status has already changed to DRAFT in the API response.
            # Release the flag only after the old worker is no longer using audio.
            m.processing_cancel_requested = False
            m.processing_error = ""
            m.save(update_fields=["processing_cancel_requested", "processing_error"])
            # Remove the incorrect uploaded file only once the worker has stopped using it.
            if m.audio:
                m.audio.delete(save=False)
                m.audio = None
                m.save(update_fields=["audio"])
            Transcript.objects.filter(meeting=m).delete()
            audit(None, "PROCESSING_CANCELLED", m)


def run(meeting_id):
    close_old_connections()
    m = Meeting.objects.get(pk=meeting_id)
    try:
        check_not_cancelled(meeting_id)
        links = list(m.links.select_related("user"))
        users = [l.user for l in links]
        progress.set_stage(m.id, "transcribing")
        text, source = get_transcriber().transcribe(m.audio.path, users)
        check_not_cancelled(meeting_id)
        progress.set_stage(m.id, "masking")
        sanitized = sanitize(text, [(l.user, l.pseudonym) for l in links])
        check_not_cancelled(meeting_id)
        Transcript.objects.update_or_create(meeting=m, defaults=dict(
            original_text=text, sanitized_text=sanitized, source=source))

        check_not_cancelled(meeting_id)
        progress.set_stage(m.id, "analyzing")
        analysis, generated_by, model_name = analyze(sanitized, m.scheduled_at)

        check_not_cancelled(meeting_id)
        progress.set_stage(m.id, "drafting")
        items = []
        for it in analysis.action_items:
            d = it.model_dump()
            try:
                date.fromisoformat(d["deadline"]) if d["deadline"] else None
            except ValueError:
                d["deadline"] = None
            d["assignee_id"] = match_participant(d["assignee"], links)
            # if d["assignee_id"] is None and len(links) == 1:
            #     # Only one person was in the meeting: suggest them. The manager still confirms on the review screen.
            #     d["assignee_id"] = links[0].user_id
            #     d["uncertainty_note"] = (d.get("uncertainty_note", "") + " Suggested the only participant as assignee; please confirm.").strip()
            # d["needs_review"] = d["assignee_id"] is None or d["deadline"] is None or d["confidence"] == "LOW"
            d["needs_review"] = (
                d["assignee_id"] is None
                or d["deadline"] is None
                or d.get("confidence") == "LOW"
)
            d["discard"] = False
            items.append(d)

        with transaction.atomic():
            # Lock the row so cancellation and publishing cannot race.
            locked = Meeting.objects.select_for_update().get(pk=m.id)
            if locked.processing_cancel_requested or locked.status != "PROCESSING":
                raise ProcessingCancelled()
            version = m.outputs.count() + 1
            AIOutput.objects.create(
                meeting=m, version=version, summary=analysis.summary, mom=analysis.mom,
                discussion_points=analysis.discussion_points, decisions=analysis.decisions,
                action_items=items, generated_by=generated_by, model_name=model_name)
            m.status, m.processing_error = "PENDING_REVIEW", ""
            m.save(update_fields=["status", "processing_error"])
        notify(m.manager, "REVIEW_READY", f"Draft outputs ready: {m.title}",
               "AI-generated draft MoM and action items await your review.", f"/meetings/{m.id}/review")
        audit(None, "AI_OUTPUT_GENERATED", m, generated_by=generated_by)
    except ProcessingCancelled:
        finish_cancelled(meeting_id)
    except AIError as e:
        import traceback
        traceback.print_exc()
        _fail(m, str(e))
    except Exception:
        import traceback
        traceback.print_exc()
        _fail(m, "Processing failed (transcription or sanitization error). Check server logs.")
    finally:
        progress.clear(m.id)
        close_old_connections()


def _fail(m, msg):
    if Meeting.objects.filter(pk=m.id, processing_cancel_requested=True).exists():
        finish_cancelled(m.id)
        return
    with transaction.atomic():
        locked = Meeting.objects.select_for_update().get(pk=m.id)
        if locked.processing_cancel_requested:
            pass
        else:
            locked.status, locked.processing_error = "FAILED", msg[:300]
            locked.save(update_fields=["status", "processing_error"])
            audit(None, "PROCESSING_FAILED", locked, error=msg[:300])
            return
    finish_cancelled(m.id)
