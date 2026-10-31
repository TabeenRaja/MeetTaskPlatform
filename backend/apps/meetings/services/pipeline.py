"""Whisper -> local normalization -> local task extraction + extractive summary/minutes -> manager review. No LLM."""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction
from apps.core.services import audit
from apps.core.services import notify
from ..models import AIOutput, Meeting, Transcript
from . import extraction, progress, summary as summarizer
from .normalization import normalize_transcript
from .transcription import get_transcriber

logger = logging.getLogger(__name__)


class ProcessingCancelled(Exception):
    pass


def start(meeting_id):
    progress.set_stage(meeting_id, "queued")
    threading.Thread(target=run, args=(meeting_id,), daemon=True).start()


def check_not_cancelled(meeting_id):
    if Meeting.objects.filter(pk=meeting_id, processing_cancel_requested=True).exists():
        raise ProcessingCancelled()


def finish_cancelled(meeting_id):
    with transaction.atomic():
        m = Meeting.objects.select_for_update().get(pk=meeting_id)
        if m.processing_cancel_requested:
            m.processing_cancel_requested = False
            m.processing_error = ""
            m.save(update_fields=["processing_cancel_requested", "processing_error"])
            if m.audio:
                m.audio.delete(save=False)
                m.audio = None
                m.save(update_fields=["audio"])
            # The view hides earlier transcripts while processing or cancelled.
            Transcript.objects.filter(meeting=m).delete()
            audit(None, "PROCESSING_CANCELLED", m)


def run(meeting_id):
    close_old_connections()
    m = None
    try:
        m = Meeting.objects.get(pk=meeting_id)
        check_not_cancelled(meeting_id)
        # Fail explicitly rather than silently treating development text as audio.
        if settings.TRANSCRIBER != "whisper":
            raise RuntimeError("Set TRANSCRIBER=whisper for this pipeline.")
        users = [link.user for link in m.links.select_related("user")]
        progress.set_stage(m.id, "transcribing")
        text, source = get_transcriber().transcribe(m.audio.path, users)
        check_not_cancelled(meeting_id)
        progress.set_stage(m.id, "normalizing")
        result = normalize_transcript(text)
        check_not_cancelled(meeting_id)

        # Publish the transcript first, so it is never lost if task extraction has a problem.
        with transaction.atomic():
            locked = Meeting.objects.select_for_update().get(pk=m.id)
            if locked.processing_cancel_requested or locked.status != "PROCESSING":
                raise ProcessingCancelled()
            Transcript.objects.update_or_create(
                meeting=locked,
                defaults={
                    "original_text": text,
                    "normalized_text": result["normalized_text"],
                    "sentences": result["sentences"],
                    "sanitized_text": "",  # clear obsolete masking data on reprocess
                    "source": source,
                },
            )
            # Status stays PROCESSING until the tasks are ready, so the page keeps refreshing on its own.
            locked.processing_error = ""
            locked.save(update_fields=["processing_error"])
            audit(None, "TRANSCRIPT_NORMALIZED", locked, source=source)

        # Local rule-based task extraction (spaCy + dateparser), then a local extractive summary and minutes.
        progress.set_stage(m.id, "extracting")
        try:
            items = run_extraction(m, result["sentences"] or result["normalized_text"], users)
        except Exception:
            logger.exception("Meeting %s task extraction failed", meeting_id)
            Meeting.objects.filter(pk=m.id, status=Meeting.Status.PROCESSING).update(
                status=Meeting.Status.NORMALIZED,
                processing_error="Task extraction failed. The transcript is saved. Check server logs.")
            return
        check_not_cancelled(meeting_id)
        # Summary and minutes are a bonus: if they fail, the tasks are still published.
        try:
            docs = build_documents(m, result["sentences"] or result["normalized_text"], items, users)
        except Exception:
            logger.exception("Meeting %s summary generation failed", meeting_id)
            docs = None
        publish_items(m.id, items, docs)
    except ProcessingCancelled:
        finish_cancelled(meeting_id)
    except Exception:
        logger.exception("Meeting %s transcription/normalization failed", meeting_id)
        if m is not None:
            _fail(m, "Transcription or normalization failed. Check server logs.")
    finally:
        progress.clear(meeting_id)
        close_old_connections()


def run_extraction(meeting, sentences, users):
    """Return action items (list of dicts) for one meeting. Also used by the extract_tasks command."""
    people = extraction.people_from_users(users)
    items = extraction.extract_action_items(sentences, people, meeting.scheduled_at)
    if len(users) == 1:
        # Only one possible owner: fill it in, but keep the item flagged for the manager.
        only = users[0]
        name = (only.get_full_name() or only.username).strip()
        for it in items:
            if it["assignee_id"] is None:
                it["assignee_id"], it["assignee"] = only.id, name
                it["uncertainty_note"] = (it["uncertainty_note"] + " Assigned to the only participant.").strip()
                it["needs_review"] = not it["deadline"] or it["confidence"] == "LOW"
    return items


def build_documents(meeting, sentences, items, users):
    """Return {"summary", "mom", "discussion_points", "decisions"} for one meeting (local, extractive)."""
    names = [(u.get_full_name() or u.username).strip() for u in users]
    return summarizer.build_summary(sentences, items, meeting, names)


def publish_items(meeting_id, items, docs=None):
    docs = docs or {}
    with transaction.atomic():
        locked = Meeting.objects.select_for_update().get(pk=meeting_id)
        if locked.processing_cancel_requested or locked.status not in (Meeting.Status.PROCESSING, Meeting.Status.NORMALIZED):
            return None
        last = locked.outputs.order_by("-version").first()
        out = AIOutput.objects.create(
            meeting=locked, version=(last.version + 1) if last else 1,
            status=AIOutput.Status.PENDING_REVIEW, summary=docs.get("summary", ""), mom=docs.get("mom", ""),
            discussion_points=docs.get("discussion_points", []), decisions=docs.get("decisions", []),
            action_items=items, generated_by="rules",
            model_name=extraction.MODEL_NAME + ("+" + summarizer.MODEL_NAME if docs else ""))
        locked.status = Meeting.Status.PENDING_REVIEW
        locked.processing_error = ""
        locked.save(update_fields=["status", "processing_error"])
        audit(None, "TASKS_EXTRACTED", locked, count=len(items), version=out.version, model=extraction.MODEL_NAME)
        notify(locked.manager, "REVIEW_READY", f"Tasks ready for review: {locked.title}",
               f"{len(items)} possible task(s) were found. Please review and approve.",
               link=f"/meetings/{locked.id}/review", dedupe_key=f"review-ready-{out.id}")
        return out


def _fail(m, msg):
    with transaction.atomic():
        locked = Meeting.objects.select_for_update().get(pk=m.id)
        if not locked.processing_cancel_requested:
            locked.status = Meeting.Status.FAILED
            locked.processing_error = msg[:300]
            locked.save(update_fields=["status", "processing_error"])
            audit(None, "PROCESSING_FAILED", locked, error=msg[:300])
            return
    finish_cancelled(m.id)