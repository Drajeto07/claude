"""Comment threads as Word keeps them (tracker DOCX-021). Which comment answers which,
and which are resolved, isn't in comments.xml: it is in commentsExtended, each entry
naming its comment by the paraId of the comment's last paragraph (and the comment it
answers by that one's)."""

from docx.opc.constants import RELATIONSHIP_TYPE as RT

from app.security.files import parse_xml_part

COMMENTS_EXTENDED = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
COMMENTS_EXTENDED_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
PARA_ID = "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def related_part(part, reltype: str):
    """The part `part` refers to by a relationship of that type, if it has one."""
    return next((rel.target_part for rel in part.rels.values() if rel.reltype == reltype and not rel.is_external), None)


def _root(part):
    return part.element if hasattr(part, "element") else parse_xml_part(part.blob)


def comment_paragraphs(comments) -> dict[str, str]:
    """Each comment's id -> the paraId of its last paragraph, for the comments with one."""
    ids = {}
    for comment in comments.iter(f"{_W}comment"):
        paragraphs = comment.findall(f"{_W}p")
        if comment.get(f"{_W}id") is not None and paragraphs and paragraphs[-1].get(PARA_ID):
            ids[comment.get(f"{_W}id")] = paragraphs[-1].get(PARA_ID)
    return ids


def comment_threads(part) -> dict[str, tuple[str | None, bool]]:
    """Each comment's id -> the id of the comment it answers (None if none) and whether
    it is resolved, as the document part's commentsExtended says; {} without one."""
    comments, extended = related_part(part, RT.COMMENTS), related_part(part, COMMENTS_EXTENDED)
    if comments is None or extended is None:
        return {}
    comment_of = {paragraph: comment for comment, paragraph in comment_paragraphs(_root(comments)).items()}
    threads = {}
    for entry in _root(extended).iter(f"{{{W15}}}commentEx"):
        comment = comment_of.get(entry.get(f"{{{W15}}}paraId") or "")
        if comment is not None:
            parent = comment_of.get(entry.get(f"{{{W15}}}paraIdParent") or "")
            threads[comment] = (parent if parent != comment else None, entry.get(f"{{{W15}}}done") in ("1", "true"))
    return threads
