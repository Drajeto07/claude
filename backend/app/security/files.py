"""What an uploaded file really is, judged from its bytes (корекции.docx §33).

A file's extension and the type the browser declares are only claims. A .docx
has to be a ZIP package holding a Word document, within limits on its entries
and on what they unpack to, so a zip bomb is refused before anything opens it;
a .pdf has to start as a PDF; a .txt has to be text; an image has to be the
kind of image its type says. Nothing here parses the document itself -- that
happens afterwards, on bytes that passed."""

import io
import zipfile

from lxml import etree

MB = 1024 * 1024

# ZIP packages (.docx). Word writes a few dozen entries, a picture-heavy
# document a few hundred. XML parts are parsed into memory (several times their
# size), so each has its own cap; pictures are only copied, so the total's is higher.
MAX_ZIP_ENTRIES = 1000
MAX_XML_PART_BYTES = 50 * MB
MAX_UNPACKED_BYTES = 200 * MB
# Far beyond what XML compresses to; checked for entries past RATIO_CHECK_FROM.
MAX_COMPRESSION_RATIO = 100
RATIO_CHECK_FROM = 1 * MB

_ZIP_MAGIC = b"PK\x03\x04"
# The OLE container of old .doc files and of password-protected .docx files.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# The types a browser may declare for each kind of file. Nothing, or
# application/octet-stream, means it didn't know, and the bytes decide.
_DECLARED = {
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", "application/x-zip-compressed"},
    "pdf": {"application/pdf", "application/x-pdf"},
    "txt": {"text/plain", "text/markdown", "text/x-markdown"},
}
_UNKNOWN = {"", "application/octet-stream", "binary/octet-stream"}
CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain",
}

_IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/bmp": (b"BM",),
}


class UnsafeFileError(ValueError):
    """A file refused for what it is or holds. The message is for the user; the
    API answers 400 with code "invalid_file"."""


def check_declared_type(extension: str, declared: str | None) -> None:
    media_type = (declared or "").split(";")[0].strip().lower()
    if media_type in _UNKNOWN or media_type in _DECLARED.get(extension, set()):
        return
    raise UnsafeFileError(f"The file says it is {media_type}, which doesn't match its .{extension} extension.")


def check_docx(data: bytes) -> None:
    if data.startswith(_OLE_MAGIC):
        raise UnsafeFileError("This is an old-format (.doc) or password-protected Word file. Save it as a .docx without a password and try again.")
    if not data.startswith(_ZIP_MAGIC):
        raise UnsafeFileError("This isn't a Word (.docx) file.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            entries = package.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError) as exc:
        raise UnsafeFileError("This Word file is damaged and can't be opened.") from exc
    if len(entries) > MAX_ZIP_ENTRIES:
        raise UnsafeFileError("This Word file holds too many parts to be opened safely.")
    unpacked = 0
    for entry in entries:
        parts = entry.filename.replace("\\", "/").split("/")
        if entry.filename.startswith(("/", "\\")) or ".." in parts or entry.flag_bits & 0x1:
            raise UnsafeFileError("This Word file has parts a Word document never has, so it can't be opened safely.")
        is_xml = entry.filename.endswith((".xml", ".rels"))
        too_compressed = entry.file_size > RATIO_CHECK_FROM and entry.file_size > MAX_COMPRESSION_RATIO * max(entry.compress_size, 1)
        if too_compressed or (is_xml and entry.file_size > MAX_XML_PART_BYTES):
            raise UnsafeFileError("This Word file unpacks to far more than Word files do, so it can't be opened safely.")
        unpacked += entry.file_size
    if unpacked > MAX_UNPACKED_BYTES:
        raise UnsafeFileError("This Word file unpacks to far more than Word files do, so it can't be opened safely.")
    if not any(entry.filename == "[Content_Types].xml" for entry in entries):
        raise UnsafeFileError("This isn't a Word (.docx) file.")


def check_pdf(data: bytes) -> None:
    # The header may follow a little junk; readers accept it within the first 1 KB.
    if b"%PDF-" not in data[:1024]:
        raise UnsafeFileError("This isn't a PDF file.")


def check_text(data: bytes) -> None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return  # UTF-16, whose zero bytes are part of the text
    if b"\x00" in data[:8192]:
        raise UnsafeFileError("This doesn't look like a text file.")


_CHECKS = {"docx": check_docx, "pdf": check_pdf, "txt": check_text}


def check_upload(extension: str, data: bytes, declared: str | None) -> str:
    """The file's real content type, once its bytes are what its extension says."""
    if extension not in _CHECKS:
        raise UnsafeFileError(f"Unsupported file type: '.{extension}'.")
    check_declared_type(extension, declared)
    _CHECKS[extension](data)
    return CONTENT_TYPES[extension]


def parse_xml_part(data: bytes) -> etree._Element:
    """A raw XML part of an uploaded package (the ones python-docx leaves
    unparsed): no entities resolved, no DTD or network access, and libxml2's
    limits on a single text or tree kept (no huge_tree). A new parser each time,
    since parsers hold state while they run and jobs parse in threads."""
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False))


def image_matches(content_type: str, data: bytes) -> bool:
    """Whether the bytes are the kind of image the type names (an image whose
    type lies is never stored, nor served back under that type)."""
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return data.startswith(_IMAGE_SIGNATURES.get(content_type, ()))
