"""Malformed Word files (tracker SEC-010, TEST-030): a deterministic corpus made from a
valid .docx, one way of breaking it each -- a damaged zip, each XML part cut short, parts
and relationships missing or pointing nowhere, a DTD, structures a Word file never has.
Every one must come back as the document it holds or as invalid_file: never a 500,
never a document made of half of it. The zip-level limits (bombs, too many parts, names
outside the package) are check_docx's, tested in test_security.py."""

import hashlib
import io
import re
import warnings
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_MACRO_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"

# The ones that are still Word files, read as they are; every other one is refused.
READABLE = frozenset(
    {
        "styles.xml missing",
        "styles based on each other",
        "a part twice",
        "relationships in a loop",
        "a huge attribute",
        "blocks nested 60 deep",
        "numbers that aren't numbers",
        "a picture that isn't one",
    }
)
# Of those, the ones whose body is the file's own: read, they hold every word of it.
SAME_TEXT = frozenset({"styles.xml missing", "styles based on each other", "a part twice", "relationships in a loop", "a huge attribute"})


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return {name: package.read(name) for name in package.namelist()}


def _zip(parts: dict[str, bytes], *, duplicate: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content)
        if duplicate is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)  # "Duplicate name": the point
                package.writestr(duplicate, parts[duplicate])
    return buffer.getvalue()


def _with(data: bytes, changes: dict[str, bytes | None], *, new: frozenset[str] = frozenset()) -> bytes:
    """The package with parts replaced (bytes) or removed (None). A part named that the
    package doesn't have is a mistake here, unless it is one of `new` -- so no variant
    silently leaves the file as it was."""
    parts = _parts(data)
    for name, content in changes.items():
        if name not in parts and name not in new:
            raise KeyError(f"the package has no {name}")
        if content is None:
            del parts[name]
        else:
            parts[name] = content
    return _zip(parts)


def _body(data: bytes, inner: str) -> bytes:
    """document.xml with its body's content replaced."""
    xml = _parts(data)["word/document.xml"].decode("utf-8")
    xml, count = re.subn(r"<w:body>.*</w:body>", lambda _: f"<w:body>{inner}<w:sectPr/></w:body>", xml, flags=re.S)
    assert count == 1
    return _with(data, {"word/document.xml": xml.encode("utf-8")})


def _nested(depth: int) -> str:
    return "<w:sdt><w:sdtContent>" * depth + "<w:p><w:r><w:t>Deep</w:t></w:r></w:p>" + "</w:sdtContent></w:sdt>" * depth


def _cut_short(content: bytes) -> bytes:
    return content[: max(1, len(content) // 2)]


def _circular(styles: bytes) -> bytes:
    """Heading 1 based on Heading 2 and Heading 2 on Heading 1."""
    for style, base in (("Heading1", "Heading2"), ("Heading2", "Heading1")):
        pattern = rb'(<w:style [^>]*w:styleId="' + style.encode() + rb'"[^>]*>)'
        styles, count = re.subn(pattern, rb'\1<w:basedOn w:val="' + base.encode() + rb'"/>', styles, count=1)
        if not count:  # the file has no such style: add it
            styles = styles.replace(
                b"</w:styles>",
                f'<w:style w:type="paragraph" w:styleId="{style}"><w:name w:val="{style}"/><w:basedOn w:val="{base}"/></w:style></w:styles>'.encode(),
            )
    return styles


def _huge(size: int) -> str:
    """`size` characters that don't compress to nothing (the zip-bomb check isn't the point)."""
    out, block = [], b"seed"
    while sum(map(len, out)) < size:
        block = hashlib.sha256(block).digest()
        out.append(block.hex())
    return "".join(out)[:size]


def _huge_attribute(document: bytes) -> bytes:
    """A first paragraph whose style id and font name are 2 MB each."""
    name = _huge(2_000_000)
    paragraph = f'<w:p><w:pPr><w:pStyle w:val="{name}"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="{name}" w:hAnsi="{name}"/></w:rPr><w:t>Huge names</w:t></w:r></w:p>'
    xml, count = re.subn(r"<w:body>", lambda _: "<w:body>" + paragraph, document.decode("utf-8"), count=1)
    assert count == 1
    return xml.encode("utf-8")


def _without_styles(parts: dict[str, bytes]) -> dict[str, bytes | None]:
    """No styles part at all -- which a package may leave out: nor its relationship, nor its type."""
    rels, count = re.subn(rb"<Relationship [^>]*Target=\"styles\.xml\"[^>]*/>", b"", parts["word/_rels/document.xml.rels"])
    types, overrides = re.subn(rb"<Override [^>]*PartName=\"/word/styles\.xml\"[^>]*/>", b"", parts["[Content_Types].xml"])
    assert count == overrides == 1
    return {"word/styles.xml": None, "word/_rels/document.xml.rels": rels, "[Content_Types].xml": types}


def _loop(parts: dict[str, bytes]) -> dict[str, bytes]:
    """document.xml related to itself, and styles.xml back to document.xml."""
    kind = "http://example.com/relationships/loop"  # a relationship type nobody knows: allowed
    rels = parts["word/_rels/document.xml.rels"].replace(
        b"</Relationships>", f'<Relationship Id="rIdLoopSelf" Type="{kind}" Target="document.xml"/></Relationships>'.encode()
    )
    back = f'<?xml version="1.0"?><Relationships xmlns="{_RELS}"><Relationship Id="rIdBack" Type="{kind}" Target="document.xml"/></Relationships>'
    return {"word/_rels/document.xml.rels": rels, "word/_rels/styles.xml.rels": back.encode()}


_BAD_NUMBERS = (
    '<w:p><w:pPr><w:ind w:left="left" w:hanging="-"/><w:spacing w:after="99999999999999999999" w:line="x"/>'
    '<w:numPr><w:ilvl w:val="99"/><w:numId w:val="-5"/></w:numPr></w:pPr><w:r><w:rPr><w:sz w:val="abc"/>'
    '<w:color w:val="nothex"/><w:w w:val="-1"/></w:rPr><w:t>Odd numbers</w:t></w:r></w:p>'
    '<w:tbl><w:tblGrid><w:gridCol w:w="none"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:gridSpan w:val="-3"/>'
    '<w:vMerge w:val="sideways"/></w:tcPr><w:p/></w:tc></w:tr></w:tbl>'
)
_BROKEN_PICTURE = (
    '<w:p><w:r><w:t>Before the picture</w:t></w:r><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
    '<wp:extent cx="-1" cy="999999999999"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rIdNowhere"/></pic:blipFill>'
    "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
)
# Entities that expand to a thousand times their size: a DTD, which no Word file has.
_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
    f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&c;</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'
)


def with_part(valid: bytes, name: str, content: bytes) -> bytes:
    """`valid` with its part `name` replaced by `content`."""
    return _with(valid, {name: content})


def with_entity(valid: bytes, url: str) -> bytes:
    """document.xml whose text is an external entity: `url`'s content, if anything read it."""
    xml = f'<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY e SYSTEM "{url}">]><w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Text &e; more</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'
    return _with(valid, {"word/document.xml": xml.encode("utf-8")})


def variants(valid: bytes) -> dict[str, bytes]:
    """Each way of breaking `valid`, by name."""
    parts = _parts(valid)
    types = parts["[Content_Types].xml"]
    assert _MAIN.encode() in types
    corpus = {
        "truncated in the middle": valid[: len(valid) // 2],
        "truncated central directory": valid[:-60],
        "a zip of garbage": b"PK\x03\x04" + bytes(range(256)) * 8,
        "document.xml empty": _with(valid, {"word/document.xml": b""}),
        "document.xml not WordprocessingML": _with(valid, {"word/document.xml": b'<?xml version="1.0"?><html><body/></html>'}),
        "document.xml without a body": _with(valid, {"word/document.xml": f'<?xml version="1.0"?><w:document xmlns:w="{W}"/>'.encode()}),
        "document.xml missing": _with(valid, {"word/document.xml": None}),
        "no relationships": _with(valid, {"_rels/.rels": None}),
        "no content types": _with(valid, {"[Content_Types].xml": None}),
        "a macro document's content type": _with(valid, {"[Content_Types].xml": types.replace(_MAIN.encode(), _MACRO_MAIN.encode())}),
        "a relationship to a missing part": _with(
            valid,
            {
                "word/_rels/document.xml.rels": parts["word/_rels/document.xml.rels"].replace(
                    b"</Relationships>",
                    b'<Relationship Id="rIdMissing" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="missing.xml"/></Relationships>',
                )
            },
        ),
        "a DTD with entities that expand": _with(valid, {"word/document.xml": _LAUGHS.encode("utf-8")}),
        "a DTD it doesn't use": _with(
            valid,
            {
                "word/document.xml": re.sub(
                    rb"(<\?xml[^>]*\?>)", rb'\1<!DOCTYPE w:document [<!ENTITY unused "x">]>', parts["word/document.xml"], count=1
                )
            },
        ),
        "blocks nested 3000 deep": _body(valid, _nested(3000)),
        # Still Word files (READABLE):
        "styles.xml missing": _with(valid, _without_styles(parts)),
        "styles based on each other": _with(valid, {"word/styles.xml": _circular(parts["word/styles.xml"])}),
        "a part twice": _zip(parts, duplicate="word/document.xml"),
        "relationships in a loop": _with(valid, _loop(parts), new=frozenset({"word/_rels/styles.xml.rels"})),
        "a huge attribute": _with(valid, {"word/document.xml": _huge_attribute(parts["word/document.xml"])}),
        "blocks nested 60 deep": _body(valid, _nested(60)),
        "numbers that aren't numbers": _body(valid, _BAD_NUMBERS),
        "a picture that isn't one": _body(valid, _BROKEN_PICTURE),
    }
    for name in parts:  # every XML part, cut short
        if name.endswith((".xml", ".rels")):
            corpus[f"{name} cut short"] = _with(valid, {name: _cut_short(parts[name])})
    return corpus
