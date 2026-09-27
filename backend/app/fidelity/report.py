"""The Document Fidelity Report (brief §17, §90): what an import, an edit or an
export changed, kept only approximately, could not keep, or refused -- each item
with the feature, the elements it concerns, the state before and after, how sure
the detection is, and why. Alongside it, the content check: "No content changes"
is only ever said when an independent comparison of the source's words with the
result's found them equal."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import Field, computed_field

from app.models.base import ApiModel


class FidelityPolicy(str, Enum):
    """How the platform handles a feature it met (brief §90)."""

    NOT_DETECTED = "not_detected"  # the platform can't see it at all (capability level)
    DETECTED_PRESERVED = "detected_preserved"  # kept as it was, editable
    DETECTED_NOT_EDITABLE = "detected_not_editable"  # kept for export, not editable in the app
    LOSSY = "lossy"  # kept, but changed or approximated
    UNSUPPORTED = "unsupported"  # left out
    BLOCKED = "blocked"  # the operation was refused rather than lose it


# What a person should look at before trusting the result.
REVIEW_POLICIES = frozenset({FidelityPolicy.LOSSY, FidelityPolicy.UNSUPPORTED, FidelityPolicy.BLOCKED})


class FidelityStage(str, Enum):
    IMPORT = "import"
    EDIT = "edit"
    FORMAT = "format"
    EXPORT = "export"
    AI = "ai"
    TRANSLATION = "translation"


class FidelityItem(ApiModel):
    # A stable key ("docx.hidden_text", "docx.image.linked"): what the capability
    # matrix, tests and the UI group by.
    feature: str = Field(max_length=100)
    policy: FidelityPolicy
    reason: str = Field(max_length=1000)
    # The top-level elements it concerns, when known (the editor can show them).
    elementIds: list[str] = Field(default_factory=list)
    sourceState: Optional[str] = Field(default=None, max_length=500)
    newState: Optional[str] = Field(default=None, max_length=500)
    # 1.0: read from the file itself; lower: inferred.
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    count: int = Field(default=1, ge=1)
    # Words, pictures or other content were lost or changed -- not only their look.
    contentChanged: bool = False


class ContentDifference(ApiModel):
    kind: Literal["missing", "added", "changed", "moved"]
    source: str = ""
    result: str = ""
    # A few words of the source just before the difference, to find it.
    context: str = ""


class ContentCheck(ApiModel):
    """The source's words against the result's, compared in order."""

    method: str
    verified: bool
    sourceWords: int
    resultWords: int
    missing: int = 0
    added: int = 0
    moved: int = 0
    samples: list[ContentDifference] = Field(default_factory=list)


class FidelityReport(ApiModel):
    stage: FidelityStage
    sourceType: str
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    items: list[FidelityItem] = Field(default_factory=list)
    # None: there was no independent source to compare with, so nothing is claimed.
    content: Optional[ContentCheck] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def contentStatus(self) -> Literal["verified", "changed", "unverified"]:
        if self.content is None:
            return "unverified"
        return "verified" if self.content.verified else "changed"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reviewCount(self) -> int:
        return sum(1 for item in self.items if item.policy in REVIEW_POLICIES)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def contentLossCount(self) -> int:
        """Items that lost or changed content outside the words compared (a
        header's text, a picture): "No content changes" is off while any exist."""
        return sum(1 for item in self.items if item.contentChanged and item.policy in REVIEW_POLICIES)


class ReportBuilder:
    """Collects items, one per feature and reason: a repeat adds to the count and
    the elements instead of a new line."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], FidelityItem] = {}

    def add(
        self,
        feature: str,
        policy: FidelityPolicy,
        reason: str,
        *,
        element_id: str | None = None,
        source: str | None = None,
        new: str | None = None,
        confidence: float = 1.0,
        content_changed: bool = False,
        count: int = 1,
    ) -> None:
        key = (feature, reason)
        item = self._items.get(key)
        if item is None:
            self._items[key] = FidelityItem(
                feature=feature,
                policy=policy,
                reason=reason,
                elementIds=[element_id] if element_id else [],
                sourceState=source,
                newState=new,
                confidence=confidence,
                count=count,
                contentChanged=content_changed,
            )
            return
        item.count += count
        if element_id and element_id not in item.elementIds:
            item.elementIds.append(element_id)

    def extend(self, items: list[FidelityItem]) -> None:
        for item in items:
            self.add(
                item.feature,
                item.policy,
                item.reason,
                source=item.sourceState,
                new=item.newState,
                confidence=item.confidence,
                content_changed=item.contentChanged,
                count=item.count,
            )
            merged = self._items[(item.feature, item.reason)]
            for element_id in item.elementIds:
                if element_id not in merged.elementIds:
                    merged.elementIds.append(element_id)

    def items(self) -> list[FidelityItem]:
        return list(self._items.values())
