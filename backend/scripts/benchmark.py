"""Benchmarks (PERF-002): how long, and how much Python memory, the heavy paths take,
so a later change can be shown to help or to hurt. Not part of the test run.

    python -m scripts.benchmark                 # everything, writes docs/performance/benchmarks.{md,json}
    python -m scripts.benchmark --quick         # small documents, one repeat: a minute, not an hour
    python -m scripts.benchmark --only save,load --timeout 300

What is measured (each case in its own child process, with a time limit, so one that
never ends is reported as timed out instead of hanging the run):

  import   every golden fixture (tests/fixtures/documents) and every Word-authored fixture
           (tests/fixtures/word) through the upload path (build_document_from_docx)
  export   Word and PDF download (GET /export/docx, /export/pdf) of a synthetic document
  save     PUT /documents/{id}/content of a synthetic document, through the API
  load     GET /documents/{id}

Synthetic documents are document-model JSON written directly in this file (the shape
the editor sends), plus pictures made with Pillow: `blocks-500`, `blocks-2000`,
`blocks-5000` (paragraphs, headings and lists in Bulgarian), `table-500x8` (one table of
500 rows by 8 columns) and `pictures-50` (50 inline PNGs, as the editor pastes them).

Everything runs on SQLite in a temporary directory, with the API in-process through
TestClient (the way tests/conftest.py builds it): no real database, no network, no AI.

Time is time.perf_counter around the call: the best and the median of the repeats.
Memory is tracemalloc's peak over one more run, so only Python's allocations -- not
what C extensions (lxml, Pillow, SQLite) allocate themselves -- and tracemalloc slows
that run, which is why it isn't one of the timed ones. A run slower than
SLOW_SECONDS is timed once and its memory is not measured."""

import argparse
import base64
import io
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FIXTURES = BACKEND / "tests" / "fixtures"
DEFAULT_OUT = REPO / "docs" / "performance"

# A run this slow is timed once: repeating it, or running it again under tracemalloc, would
# make the benchmark itself the slow part.
SLOW_SECONDS = 20.0
RESULT_PREFIX = "BENCHMARK-RESULT:"

FULL_BLOCKS = (500, 2000, 5000)
FULL_TABLE = (500, 8)
FULL_PICTURES = 50
QUICK_BLOCKS = (500,)
QUICK_TABLE = (50, 8)
QUICK_PICTURES = 10

# Bulgarian, so the stored JSON has the characters PERF-006 is about; short enough to vary.
_SENTENCES = [
    "Договорът влиза в сила от датата на подписването му от двете страни.",
    "Изпълнителят се задължава да предаде работата в уговорения срок и в добро състояние.",
    "Всички спорове се решават по взаимно съгласие, а при невъзможност - от компетентния съд.",
    "Плащането се извършва по банков път в срок от десет работни дни след получаване на фактурата.",
    "Страните запазват правото си да прекратят споразумението с писмено предизвестие от тридесет дни.",
    "Данните на клиента се обработват в съответствие с изискванията на Общия регламент за защита на данните.",
    "Приложението съдържа таблица с цените, графика на дейностите и списък на отговорните лица.",
]
_WORDS = ["Цена", "Количество", "Срок", "Бележка", "Артикул", "Сума", "Отговорник", "Статус"]


# ---------------------------------------------------------------- synthetic documents

def _id(seed: str) -> str:
    # Stable, so two runs (or a run before and after a change) save the very same document.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"smartdoc-benchmark/{seed}"))


def _runs(text: str, bold_every: int = 0, index: int = 0) -> list[dict]:
    if bold_every and index % bold_every == 0:
        head, _, tail = text.partition(" ")
        return [{"text": head, "marks": [{"type": "bold"}]}, {"text": " " + tail, "marks": []}]
    return [{"text": text, "marks": []}]


def blocks_document(count: int) -> list[dict]:
    """`count` blocks: a heading in ten, a three-item list in twenty-five, the rest paragraphs."""
    elements: list[dict] = []
    for index in range(count):
        sentence = _SENTENCES[index % len(_SENTENCES)]
        text = f"{sentence} {_SENTENCES[(index * 3 + 1) % len(_SENTENCES)]}"
        base = {"id": _id(f"block-{index}"), "order": index, "ordered": False}
        if index % 10 == 0:
            title = f"Раздел {index // 10 + 1}. {_WORDS[index % len(_WORDS)]}"
            elements.append({**base, "type": "heading", "content": title, "level": 1 + (index // 10) % 3, "inline": _runs(title)})
        elif index % 25 == 1:
            items = [{"id": _id(f"item-{index}-{n}"), "inline": _runs(_SENTENCES[(index + n) % len(_SENTENCES)]), "level": 0} for n in range(3)]
            content = "\n".join(item["inline"][0]["text"] for item in items)
            elements.append({**base, "type": "list", "content": content, "listItems": items})
        else:
            elements.append({**base, "type": "paragraph", "content": text, "inline": _runs(text, bold_every=4, index=index)})
    return elements


def table_document(rows: int, columns: int) -> list[dict]:
    """A heading, one table of rows x columns, a closing paragraph."""
    table_rows = []
    lines = []
    for row in range(rows):
        cells = []
        texts = []
        for column in range(columns):
            text = f"{_WORDS[column % len(_WORDS)]} {row + 1}.{column + 1}" if row else _WORDS[column % len(_WORDS)]
            texts.append(text)
            cells.append({"id": _id(f"cell-{row}-{column}"), "inline": _runs(text), "header": row == 0, "colspan": 1, "rowspan": 1})
        table_rows.append({"id": _id(f"row-{row}"), "cells": cells})
        lines.append(" | ".join(texts))
    title = "Таблица с цените"
    return [
        {"id": _id("table-title"), "type": "heading", "content": title, "level": 1, "inline": _runs(title), "order": 0, "ordered": False},
        {"id": _id("table"), "type": "table", "content": "\n".join(lines), "order": 1, "ordered": False,
         "table": {"rows": table_rows, "hasHeaderRow": True}},
        {"id": _id("table-end"), "type": "paragraph", "content": _SENTENCES[0], "inline": _runs(_SENTENCES[0]), "order": 2, "ordered": False},
    ]


def _png(seed: int, width: int = 160, height: int = 120) -> bytes:
    # Noise, so the PNG doesn't compress to nothing the way a flat colour would.
    from PIL import Image

    generator = random.Random(seed)
    image = Image.frombytes("RGB", (width, height), generator.randbytes(width * height * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def pictures_document(count: int) -> list[dict]:
    """`count` pictures, each under a caption paragraph, as the editor pastes them: data: URIs."""
    elements: list[dict] = []
    for index in range(count):
        caption = f"Снимка {index + 1}. {_SENTENCES[index % len(_SENTENCES)]}"
        elements.append({"id": _id(f"cap-{index}"), "type": "paragraph", "content": caption, "inline": _runs(caption),
                         "order": 2 * index, "ordered": False})
        source = "data:image/png;base64," + base64.b64encode(_png(index)).decode("ascii")
        elements.append({"id": _id(f"pic-{index}"), "type": "image", "content": "", "order": 2 * index + 1, "ordered": False,
                         "image": {"src": source, "mime": "image/png", "alt": f"Снимка {index + 1}", "widthCm": 8.0, "heightCm": 6.0}})
    return elements


def synthetic(name: str) -> list[dict]:
    kind, _, size = name.partition("-")
    if kind == "blocks":
        return blocks_document(int(size))
    if kind == "table":
        rows, _, columns = size.partition("x")
        return table_document(int(rows), int(columns))
    if kind == "pictures":
        return pictures_document(int(size))
    raise ValueError(f"unknown synthetic document {name!r}")


# ---------------------------------------------------------------- measuring

def measure(call: Callable[[], object], repeats: int, slow_seconds: float = SLOW_SECONDS) -> dict:
    """Times `call` `repeats` times, then once more under tracemalloc."""
    runs = []
    for _ in range(repeats):
        started = time.perf_counter()
        call()
        runs.append(time.perf_counter() - started)
        if runs[-1] > slow_seconds:
            return {"runs_s": runs, "best_s": min(runs), "median_s": statistics.median(runs), "peak_kib": None,
                    "note": f"one run took over {slow_seconds:.0f} s: timed once, memory not measured"}
    tracemalloc.start()
    try:
        call()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return {"runs_s": runs, "best_s": min(runs), "median_s": statistics.median(runs), "peak_kib": round(peak / 1024), "note": ""}


# ---------------------------------------------------------------- the API under test

class Harness:
    """The app on a temporary SQLite file and asset folder, signed in as a throwaway
    user -- built the way tests/conftest.py's api_db does."""

    def __init__(self, directory: Path) -> None:
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine, event
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.pool import NullPool

        from app.db.models import Base
        from app.db.session import get_db, make_engine
        from app.db.types import dump_json
        from app.jobs.queue import get_job_backend, get_job_session_factory
        from app.main import app
        from app.storage.factory import get_storage_provider
        from app.storage.local_provider import LocalStorageProvider

        def foreign_keys(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self._app = app
        self._overrides = (get_db, get_storage_provider, get_job_backend, get_job_session_factory)
        db_path = directory / "benchmark.db"
        self.engine = create_engine(f"sqlite:///{db_path}", json_serializer=dump_json)
        event.listen(self.engine, "connect", foreign_keys)
        Base.metadata.create_all(self.engine)
        async_engine = make_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)  # the app's own engine settings
        event.listen(async_engine.sync_engine, "connect", foreign_keys)
        session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

        async def override_get_db():
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_storage_provider] = lambda: LocalStorageProvider(directory / "assets")
        app.dependency_overrides[get_job_backend] = lambda: "eager"
        app.dependency_overrides[get_job_session_factory] = lambda: session_factory
        self.client = TestClient(app, base_url="https://testserver")
        response = self.client.post("/api/v1/auth/register", json={"email": "benchmark@example.com", "password": "long enough password"})
        assert response.status_code == 201, response.text

    def close(self) -> None:
        for dependency in self._overrides:
            self._app.dependency_overrides.pop(dependency, None)
        self.client.close()
        self.engine.dispose()

    def new_document(self) -> str:
        response = self.client.post("/api/v1/documents", json={"text": "# Бенчмарк\n\nПърви абзац на документа за измерване."})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def stored_bytes(self, document_id: str) -> dict:
        """The bytes the JSON columns hold as text (SQLite stores them as text; CAST to
        BLOB makes length() count bytes, not characters). A version is stored compressed
        (PERF-004) unless it is from before that; its bytes are whichever copy it holds."""
        from sqlalchemy import text

        with self.engine.connect() as connection:
            current = connection.execute(text("SELECT length(CAST(data AS BLOB)) FROM documents WHERE id = :id"), {"id": document_id}).scalar()
            versions = connection.execute(
                text(
                    "SELECT COALESCE(SUM(COALESCE(length(compressed_data), length(CAST(data AS BLOB)))), 0), COUNT(*) "
                    "FROM document_versions WHERE document_id = :id"
                ),
                {"id": document_id},
            ).one()
        return {"document_bytes": current, "version_bytes": versions[0], "version_rows": versions[1]}


def _body(elements: list[dict]) -> bytes:
    return json.dumps({"elements": elements}, ensure_ascii=False).encode("utf-8")


def _save(harness: Harness, document_id: str, body: bytes):
    response = harness.client.put(f"/api/v1/documents/{document_id}/content", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200, response.text[:300]
    return response


# ---------------------------------------------------------------- the cases (each runs in a child process)

def case_import(directory: str, repeats: int, limit: int | None = None) -> dict:
    from app.services.ingestion_service import build_document_from_docx

    files = sorted((FIXTURES / directory).glob("*.docx"))[:limit]
    results = []
    for path in files:
        data = path.read_bytes()
        document = build_document_from_docx(data, path.name, None)
        outcome = measure(lambda: build_document_from_docx(data, path.name, None), repeats)
        outcome.update(case=path.name, file_bytes=len(data), blocks=len(document.elements))
        results.append(outcome)
    return {"items": results}


def case_save_load(name: str, repeats: int) -> dict:
    elements = synthetic(name)
    body = _body(elements)
    with tempfile.TemporaryDirectory(prefix="smartdoc-bench-") as directory:
        harness = Harness(Path(directory))
        try:
            document_id = harness.new_document()
            _save(harness, document_id, body)  # the first save stores the pictures and builds the document's own copy
            save = measure(lambda: _save(harness, document_id, body), repeats)
            save["request_bytes"] = len(body)
            loaded = harness.client.get(f"/api/v1/documents/{document_id}")
            assert loaded.status_code == 200
            load = measure(lambda: harness.client.get(f"/api/v1/documents/{document_id}"), repeats)
            load.update(response_bytes=len(loaded.content), content_type=loaded.headers.get("content-type"))
            return {"save": save, "load": load, "stored": harness.stored_bytes(document_id), "blocks": len(elements)}
        finally:
            harness.close()


def case_export(name: str, kind: str, repeats: int) -> dict:
    elements = synthetic(name)
    with tempfile.TemporaryDirectory(prefix="smartdoc-bench-") as directory:
        harness = Harness(Path(directory))
        try:
            document_id = harness.new_document()
            _save(harness, document_id, _body(elements))
            url = f"/api/v1/documents/{document_id}/export/{kind}"
            size = []

            def export() -> None:
                response = harness.client.get(url)
                assert response.status_code == 200, response.text[:300]
                size.append(len(response.content))

            outcome = measure(export, repeats)
            outcome["output_bytes"] = size[-1]
            return outcome
        finally:
            harness.close()


def run_worker(args: argparse.Namespace) -> None:
    """The child process: runs one case and prints its result as one JSON line."""
    # Before the app is imported (it reads its settings then): a throwaway database
    # whatever backend/.env says, no AI, no Stripe, no rate limits (one address saves many times).
    database = f"sqlite+aiosqlite:///{(Path(tempfile.gettempdir()) / 'smartdoc-benchmark-unused.db').as_posix()}"
    os.environ.update({"DATABASE_URL": database, "ALEMBIC_DATABASE_URL": database, "STORAGE_BACKEND": "local", "REDIS_URL": "",
                       "ANTHROPIC_API_KEY": "", "STRIPE_SECRET_KEY": "", "STRIPE_WEBHOOK_SECRET": "", "RATE_LIMIT_BACKEND": "memory",
                       **{f"RATE_LIMIT_{scope}": "" for scope in ("GLOBAL", "LOGIN", "LOGIN_ACCOUNT", "REGISTER", "AI", "UPLOAD", "EXPORT")}})
    sys.path.insert(0, str(BACKEND))
    kind, *params = args.worker
    if kind == "import":
        result = case_import(params[0], args.repeats, args.limit)
    elif kind == "save-load":
        result = case_save_load(params[0], args.repeats)
    elif kind == "export":
        result = case_export(params[0], params[1], args.repeats)
    else:
        raise SystemExit(f"unknown worker {kind!r}")
    print(RESULT_PREFIX + json.dumps(result), flush=True)


# ---------------------------------------------------------------- the parent: runs the cases, writes the report

def run_case(worker: list[str], args: argparse.Namespace, repeats: int) -> dict:
    command = [sys.executable, "-m", "scripts.benchmark", "--worker", *worker, "--repeats", str(repeats)]
    if args.limit:
        command += ["--limit", str(args.limit)]
    started = time.perf_counter()
    try:
        done = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "note": f"killed after the {args.timeout:.0f} s limit", "wall_s": time.perf_counter() - started}
    wall = time.perf_counter() - started
    lines = [line for line in done.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if done.returncode != 0 or not lines:
        return {"status": "error", "note": (done.stderr.strip().splitlines() or ["no output"])[-1][:300], "wall_s": wall}
    return {"status": "ok", "wall_s": wall, **json.loads(lines[-1][len(RESULT_PREFIX):])}


def machine() -> dict:
    cpu = platform.processor() or "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.partition(":")[2].strip()
                break
    except OSError:
        pass
    ram = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                ram = round(int(line.split()[1]) / 1024 / 1024, 1)
                break
    except OSError:
        pass
    if ram is None and hasattr(os, "sysconf"):
        try:
            ram = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
        except (ValueError, OSError):
            pass
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip() or "unknown"
    # Only the tracked files count: this script's own output is rewritten by the run.
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", "backend/app"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {"cpu": cpu, "cores": os.cpu_count(), "ram_gib": ram, "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(), "git_commit": commit + (" (backend/app has uncommitted changes)" if dirty else "")}


def _seconds(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 1000:.0f} ms" if value < 1 else f"{value:.2f} s"


def _kib(value: int | None) -> str:
    if value is None:
        return "not measured"
    return f"{value / 1024:.1f} MiB" if value >= 1024 else f"{value} KiB"


def render_markdown(report: dict) -> str:
    info, results = report["machine"], report["results"]
    lines = [
        "# Benchmarks",
        "",
        f"Made by `python -m scripts.benchmark` ({report['generated']}); how to run and read it: [README.md](README.md).",
        "",
        "## Machine",
        "",
        f"- CPU: {info['cpu']}, {info['cores']} cores",
        f"- RAM: {info['ram_gib']} GiB",
        f"- OS: {info['os']}",
        f"- Python: {info['python']}",
        f"- Code: git commit {info['git_commit']}",
        f"- Options: {report['options']}",
        "",
        "**Timings are noisy.** This machine ran other jobs at the same time (other test runs and builds), so read a "
        "difference under about 20% as noise; the best of the repeats is the least disturbed number. Memory is "
        "tracemalloc's peak: Python allocations only, not what lxml, Pillow or SQLite allocate themselves.",
        "",
    ]
    skipped = [r for r in results if r["status"] != "ok"]
    if skipped:
        lines += ["## Not finished", ""]
        lines += [f"- `{r['id']}`: {r['status']}, {r['note']} (waited {r['wall_s']:.0f} s)" for r in skipped]
        lines.append("")
    for title, group in (("Import", "import"), ("Export", "export"), ("Save (PUT /content)", "save"), ("Load (GET)", "load")):
        rows = [r for r in results if r["group"] == group and r["status"] == "ok"]
        if not rows:
            continue
        lines += [f"## {title}", ""]
        if group == "import":
            lines += ["| Fixture | File | Blocks | Best | Median | Peak memory |", "|---|---:|---:|---:|---:|---:|"]
            lines += [f"| {r['id']} | {r['file_bytes']:,} B | {r['blocks']} | {_seconds(r['best_s'])} | {_seconds(r['median_s'])} | {_kib(r['peak_kib'])} |" for r in rows]
        elif group == "export":
            lines += ["| Document | Format | Output | Best | Median | Peak memory |", "|---|---|---:|---:|---:|---:|"]
            lines += [f"| {r['document']} | {r['format']} | {r['output_bytes']:,} B | {_seconds(r['best_s'])} | {_seconds(r['median_s'])} | {_kib(r['peak_kib'])} |" for r in rows]
        elif group == "save":
            lines += ["| Document | Request body | documents.data stored | Best | Median | Peak memory |", "|---|---:|---:|---:|---:|---:|"]
            lines += [f"| {r['document']} | {r['request_bytes']:,} B | {r['document_bytes']:,} B | {_seconds(r['best_s'])} | {_seconds(r['median_s'])} | {_kib(r['peak_kib'])} |" for r in rows]
        else:
            lines += ["| Document | Response | Best | Median | Peak memory |", "|---|---:|---:|---:|---:|"]
            lines += [f"| {r['document']} | {r['response_bytes']:,} B | {_seconds(r['best_s'])} | {_seconds(r['median_s'])} | {_kib(r['peak_kib'])} |" for r in rows]
        lines.append("")
    return "\n".join(lines)


def collect(args: argparse.Namespace) -> dict:
    only = set(args.only.split(",")) if args.only else {"import", "export", "save", "load"}
    blocks, table, pictures = (QUICK_BLOCKS, QUICK_TABLE, QUICK_PICTURES) if args.quick else (FULL_BLOCKS, FULL_TABLE, FULL_PICTURES)
    synthetic_names = [f"blocks-{n}" for n in blocks] + [f"table-{table[0]}x{table[1]}", f"pictures-{pictures}"]
    repeats = 1 if args.quick else args.repeats
    results: list[dict] = []

    def say(text: str) -> None:
        print(text, flush=True)

    if "import" in only:
        for directory in ("documents", "word"):
            say(f"import {directory} ...")
            outcome = run_case(["import", directory], args, max(repeats, 1) if args.quick else 5)
            if outcome["status"] != "ok":
                results.append({"id": f"import/{directory}", "group": "import", **outcome})
                continue
            results += [{"id": f"{directory}/{item['case']}", "group": "import", "status": "ok", "note": "", **item} for item in outcome["items"]]
    if only & {"save", "load"}:
        for name in synthetic_names:
            say(f"save/load {name} ...")
            outcome = run_case(["save-load", name], args, repeats)
            if outcome["status"] != "ok":
                results.append({"id": f"save-load/{name}", "group": "save", **outcome})
                continue
            if "save" in only:
                results.append({"id": f"save/{name}", "group": "save", "status": "ok", "document": name, **outcome["save"], **outcome["stored"], "blocks": outcome["blocks"]})
            if "load" in only:
                results.append({"id": f"load/{name}", "group": "load", "status": "ok", "document": name, **outcome["load"]})
    if "export" in only:
        for name in synthetic_names:
            for kind in ("docx", "pdf"):
                say(f"export {kind} {name} ...")
                outcome = run_case(["export", name, kind], args, repeats)
                if outcome["status"] != "ok":
                    results.append({"id": f"export/{kind}/{name}", "group": "export", "document": name, "format": kind, **outcome})
                    continue
                results.append({"id": f"export/{kind}/{name}", "group": "export", "status": "ok", "document": name, "format": kind, **outcome})
    options = f"{'--quick, ' if args.quick else ''}repeats {repeats}, limit {args.timeout:.0f} s per case, only: {', '.join(sorted(only))}"
    return {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "machine": machine(), "options": options, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quick", action="store_true", help="small documents and one repeat")
    parser.add_argument("--only", help="comma list of: import, export, save, load")
    parser.add_argument("--repeats", type=int, default=3, help="timed repeats of a case (default 3)")
    parser.add_argument("--timeout", type=float, default=600, help="seconds one case may take before it is killed and reported (default 600)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="where benchmarks.md and benchmarks.json go")
    parser.add_argument("--limit", type=int, help="import: only the first N fixtures of each folder")
    parser.add_argument("--worker", nargs="+", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        run_worker(args)
        return
    report = collect(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "benchmarks.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out_dir / "benchmarks.md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(f"Wrote {args.out_dir / 'benchmarks.md'} and benchmarks.json")


if __name__ == "__main__":
    main()
