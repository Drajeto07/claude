import asyncio
import os
from pathlib import Path

from app.storage.base import AssetNotFoundError, StorageProvider


class LocalStorageProvider(StorageProvider):
    """Blobs as plain files under one root directory (development and tests).
    The content type isn't persisted here; the DocumentAsset row carries it."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path_for(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(_atomic_write, self._path_for(key), data)

    async def get(self, key: str) -> bytes:
        path = self._path_for(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise AssetNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path_for(key).unlink, missing_ok=True)


def _atomic_write(path: Path, data: bytes) -> None:
    # Same temp-file + os.replace pattern as services/persistence.py: a crash
    # mid-write never leaves a truncated blob under the real key.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
