"""The end-to-end tests' backend cleans up after itself (tracker TEST-006): what earlier runs left
in the temporary folder goes when it starts -- never the outbox, a directory still in use or
anything that isn't one of its own."""

import os
import time

from scripts.e2e_server import STALE_HOURS, sweep


def _made(path, *, age_hours: float, database: bool = True, now: float) -> None:
    path.mkdir()
    if database:
        (path / "e2e.db").write_bytes(b"SQLite format 3\x00")
        (path / "assets").mkdir()
    when = now - age_hours * 3600
    for item in [path, *path.iterdir()]:
        os.utime(item, (when, when))


def test_earlier_runs_directories_go_and_the_rest_stays(tmp_path):
    now = time.time()
    _made(tmp_path / "smartdoc-e2e-old1", age_hours=STALE_HOURS + 1, now=now)
    _made(tmp_path / "smartdoc-e2e-empty", age_hours=STALE_HOURS + 1, database=False, now=now)
    _made(tmp_path / "smartdoc-e2e-running", age_hours=0.1, now=now)  # a server still writing to it
    _made(tmp_path / "smartdoc-e2e-outbox", age_hours=STALE_HOURS + 5, database=False, now=now)
    (tmp_path / "smartdoc-e2e-outbox" / "message.eml").write_text("kept")
    _made(tmp_path / "smartdoc-e2e-mine-too", age_hours=STALE_HOURS + 1, database=False, now=now)
    (tmp_path / "smartdoc-e2e-mine-too" / "something-else.txt").write_text("not ours")
    _made(tmp_path / "other-old", age_hours=STALE_HOURS + 9, now=now)
    (tmp_path / "smartdoc-e2e-a-file").write_text("a file, not a directory")

    removed = sweep(tmp_path, keep=(tmp_path / "smartdoc-e2e-outbox",), now=now)

    assert sorted(path.name for path in removed) == ["smartdoc-e2e-empty", "smartdoc-e2e-old1"]
    left = sorted(path.name for path in tmp_path.iterdir())
    assert left == ["other-old", "smartdoc-e2e-a-file", "smartdoc-e2e-mine-too", "smartdoc-e2e-outbox", "smartdoc-e2e-running"]
    assert (tmp_path / "smartdoc-e2e-outbox" / "message.eml").read_text() == "kept"
