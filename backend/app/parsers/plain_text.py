import re

from app.models.document import Document, DocumentMetadata, Element, ElementType, Section

_HEADING_MAX_LENGTH = 80
_SENTENCE_ENDINGS = (".", "!", "?")


def segment_plain_text(raw_text: str, title: str | None = None) -> Document:
    """Naive placeholder segmenter — NOT real structure analysis.

    Originally the default path before real AI structure analysis existed;
    now only used as the fallback when the AI structure-analysis call fails
    after retries (see app.ai.structure_analysis), so document creation never
    hard-fails just because one AI call went wrong. Rule:
      1. Split on blank lines into blocks.
      2. Collapse internal whitespace within each block.
      3. First block only, if a single line, <= 80 chars, and not ending in . ! ?
         -> `heading` (level 1). Every other block -> `paragraph`.
      4. No list/table/image/quote/caption/footnote detection.
    """
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", normalized) if b.strip()]

    section = Section(order=0)
    elements: list[Element] = []
    for index, block in enumerate(blocks):
        collapsed = re.sub(r"\s+", " ", block).strip()
        is_heading = (
            index == 0
            and "\n" not in block
            and len(collapsed) <= _HEADING_MAX_LENGTH
            and not collapsed.endswith(_SENTENCE_ENDINGS)
        )
        elements.append(
            Element(
                type=ElementType.HEADING if is_heading else ElementType.PARAGRAPH,
                content=collapsed,
                parentId=section.id,
                order=index,
                level=1 if is_heading else None,
            )
        )

    derived_title = (
        elements[0].content if elements and elements[0].type == ElementType.HEADING else "Untitled Document"
    )
    return Document(
        metadata=DocumentMetadata(title=title or derived_title),
        sections=[section],
        elements=elements,
    )
