_CM_PER_UNIT = {"cm": 1.0, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72, "px": 2.54 / 96}
_PT_PER_UNIT = {"pt": 1.0, "px": 0.75}


def to_cm(value: str, unit: str | None) -> float:
    """A length rule's value in centimetres; no unit means centimetres already.
    Raises ValueError for a non-number or a unit that isn't a fixed length."""
    factor = _CM_PER_UNIT.get((unit or "cm").strip().lower())
    if factor is None:
        raise ValueError(f"unsupported length unit {unit!r}")
    return float(value) * factor


def to_pt(value: str, unit: str | None) -> float:
    """A font-size/spacing rule's value in points; no unit means points already."""
    factor = _PT_PER_UNIT.get((unit or "pt").strip().lower())
    if factor is None:
        raise ValueError(f"unsupported size unit {unit!r}")
    return float(value) * factor
