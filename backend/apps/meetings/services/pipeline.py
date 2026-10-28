"""Whisper -> local normalization -> saved transcript. Analysis is deferred."""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction
from apps.core.services import audit
from ..models import Meeting, Transcript
from . import progress
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

        # Publish transcript and completion together; cancellation cannot publish
        # a partial result. No Gemini, PII masker, AIOutput or task creation.
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
            locked.status = Meeting.Status.NORMALIZED
            locked.processing_error = ""
            locked.save(update_fields=["status", "processing_error"])
            audit(None, "TRANSCRIPT_NORMALIZED", locked, source=source)
    except ProcessingCancelled:
        finish_cancelled(meeting_id)
    except Exception:
        logger.exception("Meeting %s transcription/normalization failed", meeting_id)
        if m is not None:
            _fail(m, "Transcription or normalization failed. Check server logs.")
    finally:
        progress.clear(meeting_id)
        close_old_connections()


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
