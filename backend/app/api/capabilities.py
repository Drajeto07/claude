from fastapi import APIRouter

from app.capabilities import MATRIX, CapabilityMatrix
from app.config import get_settings
from app.models.base import ApiModel

router = APIRouter()


class AiAvailability(ApiModel):
    # Whether AI steps call a model; False: they use their rules-based fallbacks. Never the key itself.
    configured: bool


@router.get("", response_model=CapabilityMatrix)
def capabilities() -> CapabilityMatrix:
    """What the platform does with each document feature (brief §91): import,
    edit, export, round trip, and how the fidelity report classifies it. The
    same for everyone, so no sign-in is needed."""
    return MATRIX


@router.get("/ai", response_model=AiAvailability)
def ai_availability() -> AiAvailability:
    """Whether this server has an AI provider configured, so the app labels a step AI only when a
    model really runs it (SmartDoc 2.0: no heuristic presented as AI). Public, like the matrix."""
    return AiAvailability(configured=get_settings().ai_configured)
