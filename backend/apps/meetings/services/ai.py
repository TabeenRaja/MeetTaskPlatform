from typing import Literal, Optional
from pydantic import BaseModel


class ActionItemSchema(BaseModel):
    title: str
    description: str = ""
    assignee: Optional[str] = None      # reserved for a later extraction stage
    deadline: Optional[str] = None      # YYYY-MM-DD or null
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    uncertainty_note: str = ""
    source_context: str = ""


class MeetingAnalysis(BaseModel):
    summary: str
    mom: str
    discussion_points: list[str]
    decisions: list[str]
    action_items: list[ActionItemSchema]


class AIError(Exception):
    """Safe message only. Never include transcript content."""


def analyze(*args, **kwargs):
    raise AIError("Analysis is disabled. This version performs transcription and normalization only.")
