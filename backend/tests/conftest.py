import pytest

from app.services import document_service as document_service_module
from app.services import persistence


@pytest.fixture(autouse=True)
def isolated_persistence(tmp_path, monkeypatch):
    """Every test gets its own throwaway persistence directory and a fresh
    DocumentService instance -- without this, the module-level
    `document_service` singleton (created once at import time, when
    `app.main` is first imported) would load from and write to this
    machine's *real* `backend/data/documents/` directory, silently mixing
    test-created documents into real persisted data across test runs."""
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(document_service_module, "document_service", document_service_module.DocumentService())
    # api.documents imported `document_service` by value at module load time,
    # so the reference there needs the same swap for routes to see it.
    from app.api import documents as documents_module

    monkeypatch.setattr(documents_module, "document_service", document_service_module.document_service)
    yield
