import threading
from datetime import date
from django.db import close_old_connections, transaction
from apps.core.services import audit, notify
from ..models import AIOutput, Meeting, Transcript
from .ai import AIError, analyze
from .pii import sanitize
from .transcription import get_transcriber


def start(meeting_id):
    threading.Thread(target=run, args=(meeting_id,), daemon=True).start()  # prototype; use Celery later


def run(meeting_id):
    close_old_connections()
    m = Meeting.objects.get(pk=meeting_id)
    try:
        links = list(m.links.select_related("user"))
        users = [l.user for l in links]
        text, source = get_transcriber().transcribe(m.audio.path, users)
        sanitized = sanitize(text, [(l.user, l.pseudonym) for l in links])
        Transcript.objects.update_or_create(meeting=m, defaults=dict(
            original_text=text, sanitized_text=sanitized, source=source))

        analysis, generated_by, model_name = analyze(sanitized, m.scheduled_at)

        by_ps = {l.pseudonym: l.user_id for l in links}
        items = []
        for it in analysis.action_items:
            d = it.model_dump()
            try:
                date.fromisoformat(d["deadline"]) if d["deadline"] else None
            except ValueError:
                d["deadline"] = None
            d["assignee_id"] = by_ps.get(d["assignee"])
            d["needs_review"] = d["assignee_id"] is None or d["deadline"] is None or d["confidence"] == "LOW"
            d["discard"] = False
            items.append(d)

        with transaction.atomic():
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
    except AIError as e:
        _fail(m, str(e))
    except Exception:
        _fail(m, "Processing failed (transcription or sanitization error). Check server logs.")
    finally:
        close_old_connections()


def _fail(m, msg):
    m.status, m.processing_error = "FAILED", msg[:300]
    m.save(update_fields=["status", "processing_error"])
    audit(None, "PROCESSING_FAILED", m, error=msg[:300])