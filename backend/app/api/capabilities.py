from fastapi import APIRouter

from app.capabilities import MATRIX, CapabilityMatrix

router = APIRouter()


@router.get("", response_model=CapabilityMatrix)
def capabilities() -> CapabilityMatrix:
    """What the platform does with each document feature (brief §91): import,
    edit, export, round trip, and how the fidelity report classifies it. The
    same for everyone, so no sign-in is needed."""
    return MATRIX
