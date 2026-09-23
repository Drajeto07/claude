import logging
import os
from pathlib import Path

from app.models.document import Document

logger = logging.getLogger(__name__)

# File-based, one JSON file per document -- proportionate to a single-process,
# single-user, no-DB-anywhere-else codebase (the same "no more machinery than
# the scale needs" judgment already used for the undo stack's full-snapshot
# design). Not meant to survive concurrent writers or scale past one process.
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "documents"


def _path_for(document_id: str) -> Path:
    return _DATA_DIR / f"{document_id}.json"


def save_document(document: Document) -> None:
    """Atomic write (temp file + os.replace) so a kill mid-write -- e.g.
    uvicorn --reload cycling mid-request -- can never leave a truncated file
    that breaks the next startup's load."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = _path_for(document.id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(document.model_dump_json(), encoding="utf-8")
    os.replace(tmp, target)


def load_all_documents() -> dict[str, Document]:
    """Best-effort: a document file that fails to parse is skipped and
    logged rather than taking down the whole service's startup."""
    documents: dict[str, Document] = {}
    if not _DATA_DIR.exists():
        return documents
    for path in _DATA_DIR.glob("*.json"):
        try:
            document = Document.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load persisted document from %s -- skipping", path)
            continue
        documents[document.id] = document
    return documents


def delete_document_file(document_id: str) -> None:
    _path_for(document_id).unlink(missing_ok=True)
