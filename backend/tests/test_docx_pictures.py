"""Word pictures as the model keeps them (tracker DOCX-018, brief §27): their type and
name, alt text and title apart, the size they're drawn at, what is cropped away, how
they're turned and flipped, and where a floating one sits -- imported, written back
into Word, drawn cropped and turned in a PDF."""

import io
import zipfile
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm
from PIL import Image as PILImage

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.export.pdf_export import _build_image, _build_table, build_pdf
from app.formatting.engine import recompute_styles
from app.models.document import ElementType
from app.parsers.docx import parse_docx


def _png(width: int = 200, height: int = 100) -> bytes:
    picture = PILImage.new("RGB", (width, height), "red")
    picture.paste(PILImage.new("RGB", (width // 2, height), "blue"), (width // 2, 0))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _save(word) -> bytes:
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()


def _picture_file(*, floating: bool = False) -> bytes:
    word = DocxDocument()
    word.add_paragraph("Before the picture.")
    shape = word.add_paragraph().add_run().add_picture(io.BytesIO(_png()), width=Cm(4))
    inline = shape._inline
    inline.docPr.set("descr", "A red and blue flag")
    inline.docPr.set("title", "Flag")
    inline.docPr.set("name", "flag.png")
    pic = inline.graphic.graphicData.pic
    pic.blipFill.find(qn("a:blip")).addnext(parse_xml(f'<a:srcRect {nsdecls("a")} l="25000"/>'))
    xfrm = pic.spPr.find(qn("a:xfrm"))
    xfrm.set("rot", "5400000")  # 90 degrees
    xfrm.set("flipH", "1")
    if floating:
        anchor = parse_xml(
            f'<wp:anchor {nsdecls("wp")} distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="251658240" '
            'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="margin"><wp:posOffset>720000</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="paragraph"><wp:align>top</wp:align></wp:positionV></wp:anchor>'
        )
        anchor.append(inline.find(qn("wp:extent")))
        anchor.append(parse_xml(f'<wp:wrapSquare {nsdecls("wp")} wrapText="bothSides"/>'))
        for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
            part = inline.find(qn(tag))
            if part is not None:
                anchor.append(part)
        inline.getparent().replace(inline, anchor)
    return _save(word)


GOLDEN_PICTURES = Path(__file__).parent / "fixtures" / "documents" / "17-pictures.docx"


def _picture_of(document):
    [picture] = [element.image for element in document.elements if element.type == ElementType.IMAGE]
    return picture


def test_a_pictures_size_crop_turn_and_name_are_kept():
    picture = _picture_of(parse_docx(_picture_file(), "flag.docx"))

    assert (picture.mime, picture.name, picture.alt, picture.title) == ("image/png", "flag.png", "A red and blue flag", "Flag")
    assert (picture.widthCm, picture.heightCm) == (4.0, 2.0)
    assert (picture.crop.left, picture.crop.right, picture.rotation, picture.flipHorizontal) == (0.25, 0, 90, True)
    assert picture.placement is None  # in line with the text


def test_a_floating_picture_keeps_where_it_floats_in_a_word_export():
    document = parse_docx(_picture_file(floating=True), "floating.docx")
    placement = _picture_of(document).placement

    exported = build_docx(document)
    again = _picture_of(parse_docx(exported, "again.docx"))

    assert (placement.wrap, placement.horizontalFrom, placement.horizontalCm, placement.verticalAlign, placement.distanceLeftCm) == (
        "square",
        "margin",
        2.0,
        "top",
        0.32,
    )
    assert package_problems(exported) == []
    assert again.placement == placement
    assert "docx.image.floating" in {item.feature for item in document.importReport.items}


def test_a_word_export_writes_crop_turn_and_flips_back():
    document = parse_docx(_picture_file(), "flag.docx")

    exported = build_docx(document)
    again = _picture_of(parse_docx(exported, "again.docx"))

    assert package_problems(exported) == []
    kept = ("mime", "name", "alt", "title", "widthCm", "heightCm", "crop", "rotation", "flipHorizontal", "flipVertical", "placement")
    assert again.model_dump(include=set(kept)) == _picture_of(document).model_dump(include=set(kept))


def test_an_unchanged_picture_keeps_its_exact_size_and_a_new_width_rule_still_wins():
    document = parse_docx(_picture_file(), "flag.docx")
    recompute_styles(document)  # as an upload does: its width is a rule now, a share of the text width
    [element] = [element for element in document.elements if element.type == ElementType.IMAGE]
    assert document.resolvedStyles[element.styleRef]["width"] == "26.2%"  # 4 cm of 15.24

    again = _picture_of(parse_docx(build_docx(document), "again.docx"))
    document.resolvedStyles[element.styleRef]["width"] = "50%"
    resized = _picture_of(parse_docx(build_docx(document), "resized.docx"))

    assert (again.widthCm, again.heightCm) == (4.0, 2.0)  # not 26.2% of the text width: 3.99 cm
    assert (resized.widthCm, resized.heightCm) == (7.62, 3.81)  # half the text width, in proportion


def test_a_turned_picture_takes_the_room_of_its_turned_outline():
    document = parse_docx(_picture_file(), "flag.docx")  # 4 by 2 cm, turned a quarter
    [element] = [element for element in document.elements if element.type == ElementType.IMAGE]

    with zipfile.ZipFile(io.BytesIO(build_docx(document))) as package:
        body = package.read("word/document.xml").decode("utf-8")
    drawn = _build_image(element, document, {}, width=1000)

    # Word: its size stays 4 by 2 cm; each side comes in 1 cm and its top and bottom go out 1 cm.
    assert '<wp:extent cx="1440000" cy="720000"/>' in body
    assert '<wp:effectExtent l="-360000" t="360000" r="-360000" b="360000"/>' in body
    # The PDF draws it 2 cm wide and 4 cm high (in points).
    assert (round(drawn.drawWidth / 28.3465, 2), round(drawn.drawHeight / 28.3465, 2)) == (2.0, 4.0)


def test_a_pdf_draws_the_picture_cropped_and_turned():
    from pypdf import PdfReader

    pdf = build_pdf(parse_docx(_picture_file(), "flag.docx"))

    [drawn] = PdfReader(io.BytesIO(pdf)).pages[0].images
    assert drawn.image.size == (100, 150)  # 200x100, a quarter cut off the left, then turned a quarter


def test_in_a_pdf_the_text_by_a_picture_in_a_cell_keeps_the_tables_look():
    document = parse_docx(GOLDEN_PICTURES.read_bytes(), GOLDEN_PICTURES.name)
    recompute_styles(document)
    [element] = [element for element in document.elements if element.type == ElementType.TABLE]

    table = _build_table(element, document, {}, width=450)
    (text, picture), beside = table._cellvalues[0]

    # The cell's own paragraph (it holds a picture too) is drawn as the one-line cell beside
    # it is -- in the table's font and line height -- so the picture below doesn't cover it.
    assert (text.style.fontName, text.style.fontSize, text.style.leading) == (beside.style.fontName, beside.style.fontSize, beside.style.leading)
    assert text.style.leading > text.style.fontSize
    assert (round(picture.drawWidth / 28.3465, 2), round(picture.drawHeight / 28.3465, 2)) == (3.0, 2.0)
