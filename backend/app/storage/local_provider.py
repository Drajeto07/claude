import asyncio
import os
from pathlib import Path, PureWindowsPath

from app.storage.base import AssetNotFoundError, StorageProvider


class LocalStorageProvider(StorageProvider):
    """Blobs as plain files under one root directory (development and tests).
    The content type isn't persisted here; the DocumentAsset row carries it."""

    def __init__(self, root: Path) -> None:
        # The root exists before it is resolved: Windows resolves a missing path differently
        # (8.3 short names stay) from an existing one, so a provider made before the first write
        # created the folder took every key for one escaping the root (two thumbnails asked for
        # at once on a fresh server -- seen 2026-10-14).
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve()

    def _path_for(self, key: str) -> Path:
        # Checked by its parts, not by resolving the file: on Windows, resolving a file another
        # thread is writing next to can come back unnormalised (8.3 names) and look as if it were
        # outside the root -- two thumbnails drawn at once were refused that way (2026-10-14).
        parts = key.replace("\\", "/").split("/")
        if not key or PureWindowsPath(key).drive or key.startswith(("/", "\\")) or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return self._root.joinpath(*parts)

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
