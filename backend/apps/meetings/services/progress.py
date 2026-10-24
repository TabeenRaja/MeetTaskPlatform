"""Live processing progress for a meeting, kept in the cache (no database column needed).
The pipeline runs in a thread inside the web process, so the process cache is enough for this prototype;
if it moves to Celery, point CACHES at Redis and nothing else changes."""
import time
from django.core.cache import cache

# key: (label, percent when the stage starts)
STAGES = [
    ("queued", "Getting ready", 4),
    ("transcribing", "Turning the recording into text", 10),
    ("masking", "Protecting private details", 58),
    ("analyzing", "AI is reading the meeting", 68),
    ("drafting", "Drafting minutes and action items", 94),
]
_INDEX = {k: i for i, (k, _, _) in enumerate(STAGES)}


def _key(meeting_id):
    return f"meeting-progress-{meeting_id}"


def set_stage(meeting_id, stage):
    cache.set(_key(meeting_id), {"stage": stage, "since": time.time()}, 3600)


def clear(meeting_id):
    cache.delete(_key(meeting_id))


def get(meeting_id):
    """Dict for the API, or None when nothing is tracked (e.g. the server restarted mid-run)."""
    cur = cache.get(_key(meeting_id))
    if not cur or cur["stage"] not in _INDEX:
        return None
    i = _INDEX[cur["stage"]]
    nxt = STAGES[i + 1][2] if i + 1 < len(STAGES) else 100
    return {
        "stage": cur["stage"],
        "label": STAGES[i][1],
        "percent": STAGES[i][2],
        "next_percent": nxt,
        "elapsed": round(time.time() - cur["since"], 1),
        "steps": [{"key": k, "label": l} for k, l, _ in STAGES],
    }
