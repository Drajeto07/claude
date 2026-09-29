"""Builds the Word-authored fixtures in tests/fixtures/word/ (tracker TEST-020,
audit AUD-20): synthetic documents written by Microsoft Word itself, through COM,
so each file has the OOXML a real user's Word writes -- which python-docx's
golden documents (make_golden_documents.py) don't. No real personal data anywhere:
names, numbers and addresses are made up.

Each feature goes in on its own; manifest.json records what went in and what Word
refused, so a test only claims what a fixture really holds. Then each file is
scrubbed of what would identify the machine or its user (scrub).

Windows with Microsoft Word only, and never while Word is open (it refuses):

    python -m scripts.make_word_fixtures [builder ...]

Word writes different bytes every time (revision ids, dates), so the committed
files are what the tests use; rebuild them only on purpose."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile

import win32com.client as win32
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.abspath(os.path.join(HERE, "..", "tests", "fixtures", "word"))
IMG = tempfile.mkdtemp(prefix="word-fixture-images-")  # the pictures that go in; not kept
MANIFEST: dict[str, dict] = {}


def cm(value):
    return value * 72 / 2.54


def para_with(doc, prefix):
    for i in range(1, doc.Paragraphs.Count + 1):
        par = doc.Paragraphs(i)
        if par.Range.Text.startswith(prefix):
            return par
    raise LookupError(prefix)


def rgb(r, g, b):
    return r + g * 256 + b * 65536


# -- images ---------------------------------------------------------------------------


def make_images():
    def canvas(w, h, color, label):
        im = Image.new("RGB", (w, h), color)
        d = ImageDraw.Draw(im)
        for i in range(0, w, 40):
            d.line([(i, 0), (i, h)], fill=(255, 255, 255), width=2)
        d.rectangle([10, 10, w - 10, h - 10], outline=(0, 0, 0), width=6)
        d.text((30, 30), label, fill=(0, 0, 0))
        return im

    canvas(800, 400, (70, 130, 180), "PNG test").save(os.path.join(IMG, "chart.png"))
    canvas(1200, 800, (200, 120, 60), "JPEG test").save(os.path.join(IMG, "photo.jpg"), quality=85)
    canvas(300, 300, (60, 160, 90), "GIF").save(os.path.join(IMG, "anim.gif"))
    canvas(400, 300, (150, 80, 160), "WEBP").save(os.path.join(IMG, "pic.webp"))
    canvas(200, 200, (90, 90, 90), "BMP").save(os.path.join(IMG, "pic.bmp"))
    canvas(160, 160, (20, 60, 140), "LOGO").save(os.path.join(IMG, "logo.png"))
    canvas(4000, 3000, (120, 120, 200), "LARGE").save(os.path.join(IMG, "large.jpg"), quality=90)
    with open(os.path.join(IMG, "vector.svg"), "w", encoding="utf-8") as f:
        f.write(
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">'
            '<rect x="5" y="5" width="190" height="90" fill="#e0f0ff" stroke="#003366" stroke-width="4"/>'
            '<text x="30" y="60" font-size="28" fill="#003366">SVG</text></svg>'
        )


# -- Word helpers ---------------------------------------------------------------------


class Doc:
    def __init__(self, word, name):
        self.word = word
        self.name = name
        self.doc = word.Documents.Add()
        self.first = True
        self.after_table = False
        self.ok: list[str] = []
        self.failed: dict[str, str] = {}

    def p(self, text="", style=None):
        """A new paragraph just before the document's final paragraph mark, so it
        owns a mark of its own and references to it never drift (Word anchors a
        paragraph to its mark, and the final mark always stays last)."""
        end = self.doc.Content.End - 1
        self.doc.Range(end, end).InsertBefore(text + chr(13))
        par = self.doc.Range(end, end).Paragraphs(1)
        par.Style = self.doc.Styles(-1)
        par.Reset()
        par.Range.Font.Reset()
        if style is not None:
            par.Style = self.doc.Styles(style)
        return par

    def caption(self, label, title):
        """A caption the way Word writes one: Caption style, the label, a SEQ field, the title."""
        cap = self.p(f"{label} ", -35)
        self.doc.Fields.Add(self.doc.Range(cap.Range.End - 1, cap.Range.End - 1), -1, f"SEQ {label} " + chr(92) + "* ARABIC", False)
        self.doc.Range(cap.Range.End - 1, cap.Range.End - 1).InsertAfter(title)
        return cap

    def text_range(self, par):
        """The paragraph's text without its paragraph mark."""
        r = par.Range
        return self.doc.Range(r.Start, r.End - 1)

    def feature(self, name, fn):
        try:
            fn()
            self.ok.append(name)
        except Exception as exc:  # noqa: BLE001
            self.failed[name] = f"{type(exc).__name__}: {exc}"[:300]

    def table(self, rows, cols):
        anchor = self.p("")
        return self.doc.Tables.Add(anchor.Range, rows, cols)

    def end_range(self):
        end = self.doc.Content.End - 1
        return self.doc.Range(end, end)

    def save(self):
        path = os.path.join(FIX, self.name)
        if os.path.exists(path):
            os.remove(path)
        self.doc.SaveAs2(path, FileFormat=16)
        pages = self.doc.ComputeStatistics(2)
        self.doc.Close(False)
        MANIFEST[self.name] = {"ok": self.ok, "failed": self.failed, "word_pages": pages}
        print(f"{self.name}: {len(self.ok)} ok, {len(self.failed)} failed, {pages} pages")


# -- fixtures -------------------------------------------------------------------------


def f01_formatting(word):
    d = Doc(word, "a01-formatting.docx")
    doc = d.doc
    d.p("Character and paragraph formatting", -2)

    def fonts():
        for font, size in (("Times New Roman", 12), ("Arial", 11), ("Calibri", 14), ("Georgia", 10), ("Garamond", 13)):
            par = d.p(f"This sentence is set in {font} {size} pt. Тази фраза е на кирилица.")
            par.Range.Font.Name = font
            par.Range.Font.Size = size

    d.feature("font families and sizes", fonts)

    def basic():
        par = d.p("Bold italic underline strike: ")
        for text, attr in (("bold", "Bold"), ("italic", "Italic"), ("underline", "Underline"), ("strike", "StrikeThrough")):
            r = d.end_range() if False else None
            start = par.Range.End - 1
            par.Range.InsertAfter  # noqa: B018
            rng = doc.Range(start, start)
            rng.InsertAfter(text + " ")
            rng = doc.Range(start, start + len(text))
            setattr(rng.Font, attr, True)

    d.feature("bold/italic/underline/strike runs", basic)

    def underline_variants():
        par = d.p("Underline variants: double wavy dotted thick")
        base = par.Range.Start
        text = par.Range.Text
        for word_text, kind in (("double", 3), ("wavy", 11), ("dotted", 4), ("thick", 6)):
            i = text.index(word_text)
            doc.Range(base + i, base + i + len(word_text)).Font.Underline = kind

    d.feature("underline variants (double, wavy, dotted, thick)", underline_variants)

    def effects():
        par = d.p("Effects: DOUBLESTRIKE smallcaps allcaps superscript subscript hidden-text")
        base = par.Range.Start
        text = par.Range.Text

        def span(word_text):
            i = text.index(word_text)
            return doc.Range(base + i, base + i + len(word_text))

        span("DOUBLESTRIKE").Font.DoubleStrikeThrough = True
        span("smallcaps").Font.SmallCaps = True
        span("allcaps").Font.AllCaps = True
        span("superscript").Font.Superscript = True
        span("subscript").Font.Subscript = True
        span("hidden-text").Font.Hidden = True

    d.feature("double strike, small caps, all caps (text stored lowercase), super/subscript, hidden text", effects)

    def colors():
        par = d.p("Colours: red text, theme accent text, yellow highlight, grey shading")
        base = par.Range.Start
        text = par.Range.Text

        def span(word_text):
            i = text.index(word_text)
            return doc.Range(base + i, base + i + len(word_text))

        span("red text").Font.Color = rgb(200, 0, 0)
        span("theme accent text").Font.TextColor.ObjectThemeColor = 5  # accent1
        span("yellow highlight").HighlightColorIndex = 7
        span("grey shading").Font.Shading.BackgroundPatternColor = rgb(220, 220, 220)

    d.feature("RGB colour, theme colour, highlight, run shading", colors)

    def spacing():
        par = d.p("Character spacing: expanded scaled raised kerned")
        base = par.Range.Start
        text = par.Range.Text

        def span(word_text):
            i = text.index(word_text)
            return doc.Range(base + i, base + i + len(word_text))

        span("expanded").Font.Spacing = 3
        span("scaled").Font.Scaling = 150
        span("raised").Font.Position = 4
        span("kerned").Font.Kerning = 8

    d.feature("character spacing, scale, position, kerning", spacing)

    def language():
        par = d.p("Deutscher Satz mit Sprachmarkierung. Български текст с езиков маркер.")
        par.Range.LanguageID = 1031
        text = par.Range.Text
        i = text.index("Български")
        doc.Range(par.Range.Start + i, par.Range.End - 1).LanguageID = 1026

    d.feature("language tags de-DE / bg-BG", language)

    def paragraph_formatting():
        for label, value in (("Left aligned", 0), ("Centred", 1), ("Right aligned", 2), ("Justified " + "text " * 30, 3)):
            d.p(label).Alignment = value
        par = d.p("Indented both sides by 2 cm with a 1 cm first line. " * 3)
        par.LeftIndent = cm(2)
        par.RightIndent = cm(2)
        par.FirstLineIndent = cm(1)
        par = d.p("Hanging indent 1.5 cm. " * 4)
        par.LeftIndent = cm(1.5)
        par.FirstLineIndent = -cm(1.5)
        par = d.p("Spacing 18 pt before and 24 pt after.")
        par.SpaceBefore = 18
        par.SpaceAfter = 24
        par = d.p("Line spacing 1.5 lines. " * 8)
        par.LineSpacingRule = 1
        par = d.p("Line spacing exactly 20 pt. " * 8)
        par.LineSpacingRule = 4
        par.LineSpacing = 20
        par = d.p("Line spacing at least 14 pt. " * 8)
        par.LineSpacingRule = 3
        par.LineSpacing = 14

    d.feature("alignment, left/right/first-line/hanging indents, spacing, line spacing (multiple/exact/at least)", paragraph_formatting)

    def pagination_flags():
        par = d.p("Keep with next paragraph (a label that must stay with its table).")
        par.KeepWithNext = True
        par = d.p("Keep lines together. " * 10)
        par.KeepTogether = True
        par = d.p("Widow/orphan control switched OFF. " * 6)
        par.WidowControl = False
        par = d.p("Page break before this paragraph.")
        par.PageBreakBefore = True
        par = d.p("Body text with outline level 2 (not a heading style).")
        par.OutlineLevel = 2

    d.feature("keep with next, keep lines together, widow control off, page break before, outline level", pagination_flags)

    def tabs_borders():
        par = d.p("Name\tDotted leader to a right tab\t42")
        par.TabStops.ClearAll()
        par.TabStops.Add(cm(8), 0, 0)
        par.TabStops.Add(cm(16), 2, 1)
        par = d.p("A paragraph with a box border and light blue shading.")
        par.Borders.Enable = True
        par.Shading.BackgroundPatternColor = rgb(221, 235, 247)

    d.feature("tab stops with leader, paragraph border and shading", tabs_borders)

    def empty_spacing():
        d.p("Before three empty paragraphs used as spacing.")
        d.p("")
        d.p("")
        d.p("")
        d.p("After the empty paragraphs.")

    d.feature("empty paragraphs used as spacing", empty_spacing)

    def plain_urls():
        d.p("A plain-text address that is not a link: www.example.org and mail test@example.com (typed, no hyperlink).")

    d.feature("plain-text URL/e-mail that is NOT a hyperlink", plain_urls)
    d.save()


def f02_tables(word):
    d = Doc(word, "a02-tables.docx")
    doc = d.doc
    d.p("Complex tables", -2)

    def complex_table():
        d.p("Table 1: merges, widths, heights, borders, shading, alignment, repeated header")
        t = d.table(6, 4)
        d.first = False
        widths = (2, 6, 3, 4)
        for i, width_cm in enumerate(widths, start=1):
            t.Columns(i).Width = cm(width_cm)
        for r in range(1, 7):
            for c in range(1, 5):
                t.Cell(r, c).Range.Text = f"R{r}C{c}"
        t.Rows(1).HeadingFormat = True
        t.Borders.Enable = True
        t.Borders.OutsideLineWidth = 12  # 1.5 pt
        t.Rows(3).Height = 40
        t.Rows(3).HeightRule = 2
        t.Cell(3, 2).VerticalAlignment = 1
        t.Cell(3, 3).VerticalAlignment = 3
        t.Cell(2, 4).Range.ParagraphFormat.Alignment = 2
        t.Cell(2, 1).Shading.BackgroundPatternColor = rgb(255, 230, 153)
        t.LeftPadding = cm(0.4)
        t.Cell(4, 1).Merge(t.Cell(4, 2))  # horizontal
        t.Cell(5, 3).Merge(t.Cell(6, 3))  # vertical
        t.Rows.Alignment = 0  # left
        return t

    d.feature("table: explicit widths, exact row height, heading-repeat row, custom borders, shading, v/h alignment, cell margins, gridSpan + vMerge, left aligned", complex_table)

    def borderless():
        d.p("Table 2: a borderless two-column layout table (like a CV).")
        t = d.table(3, 2)
        t.Borders.Enable = False
        for r, (a, b) in enumerate((("2019-2023", "Bachelor of Testing"), ("2023-", "Master of Audits"), ("Skills", "Python, Word")), start=1):
            t.Cell(r, 1).Range.Text = a
            t.Cell(r, 2).Range.Text = b
        t.Columns(1).Width = cm(3)
        t.Columns(2).Width = cm(12)

    d.feature("borderless layout table", borderless)

    def nested_and_blocks():
        d.p("Table 3: a nested table, a bullet list and a picture inside cells.")
        t = d.table(2, 2)
        t.Borders.Enable = True
        t.Cell(1, 1).Range.Text = "Outer cell with nested table:"
        inner_at = t.Cell(1, 2).Range
        inner_at = doc.Range(inner_at.Start, inner_at.Start)
        inner = doc.Tables.Add(inner_at, 2, 2)
        for r in range(1, 3):
            for c in range(1, 3):
                inner.Cell(r, c).Range.Text = f"in{r}{c}"
        cell = t.Cell(2, 1).Range
        cell.Text = "First bullet\rSecond bullet"
        t.Cell(2, 1).Range.ListFormat.ApplyBulletDefault()
        pic_at = t.Cell(2, 2).Range
        doc.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, doc.Range(pic_at.Start, pic_at.Start))

    d.feature("nested table, bullets in a cell, picture in a cell", nested_and_blocks)

    def styled():
        d.p("Table 4: built-in table style Grid Table 4 - Accent 1 with a caption.")
        t = d.table(3, 3)
        t.Style = "Grid Table 4 - Accent 1"
        for r in range(1, 4):
            for c in range(1, 4):
                t.Cell(r, c).Range.Text = f"S{r}{c}"
        d.caption("Table", ": Styled table (caption after the table)")

    d.feature("table style + InsertCaption above", styled)

    def long_table():
        d.p("Table 5: 45 rows with a repeated header row across pages.")
        t = d.table(45, 3)
        t.Borders.Enable = True
        t.Rows(1).HeadingFormat = True
        t.Cell(1, 1).Range.Text = "No."
        t.Cell(1, 2).Range.Text = "Item"
        t.Cell(1, 3).Range.Text = "Amount"
        for r in range(2, 46):
            t.Cell(r, 1).Range.Text = str(r - 1)
            t.Cell(r, 2).Range.Text = f"Line item {r - 1}"
            t.Cell(r, 3).Range.Text = f"{(r - 1) * 12.5:.2f}"
            t.Cell(r, 3).Range.ParagraphFormat.Alignment = 2

    d.feature("45-row table with repeated header row", long_table)

    def vertical_text():
        d.p("Table 6: vertical text direction and a centred, indented table.")
        t = d.table(2, 3)
        t.Borders.Enable = True
        t.Cell(1, 1).Range.Text = "Vertical"
        t.Cell(1, 1).Range.Orientation = 2
        t.Cell(1, 2).Range.Text = "Normal"
        t.Rows.Alignment = 1

    d.feature("vertical text direction in a cell, centred table", vertical_text)
    d.p("End of tables.")
    d.save()


def f03_lists(word):
    d = Doc(word, "a03-lists.docx")
    doc = d.doc
    d.p("Lists and numbering", -2)
    gallery_outline = word.ListGalleries(3)  # wdOutlineNumberGallery

    def apply(paragraphs, template, continue_previous=False):
        rng = doc.Range(paragraphs[0].Range.Start, paragraphs[-1].Range.End)
        rng.ListFormat.ApplyListTemplate(template, continue_previous, 0)

    def custom_template(styles_formats):
        t = doc.ListTemplates.Add(True)
        for level, (style, fmt) in enumerate(styles_formats, start=1):
            lv = t.ListLevels(level)
            if style == 23:  # a bullet: the glyph and its font first, then the style
                lv.NumberFormat = fmt
                lv.Font.Name = "Arial"
            lv.NumberStyle = style
            lv.NumberFormat = fmt
            lv.NumberPosition = cm(0.63 * (level - 1))
            lv.TextPosition = cm(0.63 * level)
        return t

    def bullets():
        d.p("Custom bullet (en dash):")
        pars = [d.p(f"Dash item {i}") for i in range(1, 4)]
        rng = doc.Range(pars[0].Range.Start, pars[-1].Range.End)
        rng.ListFormat.ApplyBulletDefault()
        level = rng.ListFormat.ListTemplate.ListLevels(1)
        level.NumberFormat = "–"
        level.Font.Name = "Arial"
        rng.ListFormat.ApplyListTemplate(rng.ListFormat.ListTemplate, False, 0)

    d.feature("custom bullet character", bullets)

    def roman_letters():
        d.p("Upper roman:")
        apply([d.p(f"Roman item {i}") for i in range(1, 4)], custom_template([(1, "%1.")]))
        d.p("Lower letters:")
        apply([d.p(f"Letter item {i}") for i in range(1, 4)], custom_template([(4, "%1)")]))

    d.feature("upper roman, lower letter numbering", roman_letters)

    def legal_multilevel():
        d.p("Legal multilevel 1 / 1.1 / 1.1.1:")
        t = custom_template([(0, "%1."), (0, "%1.%2."), (0, "%1.%2.%3.")])
        pars = [d.p("Article one"), d.p("Clause one point one"), d.p("Sub-clause one one one"), d.p("Clause one point two"), d.p("Article two")]
        apply(pars, t)
        for par, level in zip(pars, (1, 2, 3, 2, 1)):
            par.Range.ListFormat.ListLevelNumber = level

    d.feature("legal multilevel numbering 1 / 1.1 / 1.1.1", legal_multilevel)

    def five_levels():
        d.p("Five nested levels (outline gallery):")
        pars = [d.p(f"Level {lvl} item") for lvl in (1, 2, 3, 4, 5, 4, 3, 2, 1)]
        apply(pars, gallery_outline.ListTemplates(1))
        for par, lvl in zip(pars, (1, 2, 3, 4, 5, 4, 3, 2, 1)):
            par.Range.ListFormat.ListLevelNumber = lvl

    d.feature("five-level nested list", five_levels)

    def restart_continue():
        t = custom_template([(0, "%1.")])
        d.p("Numbered list A (1-3):")
        apply([d.p(f"A item {i}") for i in range(1, 4)], t)
        d.p("An interrupting paragraph - the next list CONTINUES at 4.")
        apply([d.p(f"A item {i}") for i in range(4, 6)], t, continue_previous=True)
        d.p("Numbered list B restarts at 1:")
        apply([d.p(f"B item {i}") for i in range(1, 3)], custom_template([(0, "%1.")]))
        d.p("List starting at 5:")
        t5 = custom_template([(0, "%1.")])
        t5.ListLevels(1).StartAt = 5
        apply([d.p(f"C item {i}") for i in range(5, 7)], t5)

    d.feature("continuation across an interrupting paragraph, restart, start at 5", restart_continue)

    def mixed():
        d.p("Mixed: numbered level 1 with bulleted level 2:")
        t = custom_template([(0, "%1."), (23, "•")])
        pars = [d.p("Numbered one"), d.p("bullet under one"), d.p("bullet under one again"), d.p("Numbered two")]
        apply(pars, t)
        pars[1].Range.ListFormat.ListLevelNumber = 2
        pars[2].Range.ListFormat.ListLevelNumber = 2

    d.feature("mixed numbered/bulleted levels in one list", mixed)

    def numbered_headings():
        d.p("Numbered headings (outline-numbered Heading styles):")
        h = [d.p("Introduction", -2), d.p("Scope", -3), d.p("Method", -2)]
        heading_template = word.ListGalleries(3).ListTemplates(5)
        apply(h, heading_template)
        for par, lvl in zip(h, (1, 2, 1)):
            par.Range.ListFormat.ListLevelNumber = lvl

    d.feature("numbered headings", numbered_headings)

    def empty_item():
        d.p("A numbered list with an empty item in the middle:")
        t = custom_template([(0, "%1.")])
        apply([d.p("Filled one"), d.p(""), d.p("Filled three")], t)

    d.feature("empty list item", empty_item)
    d.p("End of lists.")
    d.save()


def f04_images(word):
    d = Doc(word, "a04-images.docx")
    doc = d.doc
    d.p("Images and drawing", -2)

    def add_inline(name, **kw):
        par = d.p("")
        return doc.InlineShapes.AddPicture(os.path.join(IMG, name), False, True, doc.Range(par.Range.Start, par.Range.Start))

    def alt():
        shape = add_inline("chart.png")
        shape.AlternativeText = "Blue bar chart of quarterly results"
        shape.Title = "Chart title"
        d.caption("Figure", ": A captioned PNG")

    d.feature("inline PNG with alt text + caption", alt)

    def cropped():
        shape = add_inline("photo.jpg")
        shape.Width = 300
        shape.LockAspectRatio = True
        shape.PictureFormat.CropLeft = 60
        shape.PictureFormat.CropTop = 30

    d.feature("inline JPEG cropped", cropped)

    def formats():
        for name in ("anim.gif", "pic.bmp", "vector.svg", "pic.webp"):
            try:
                add_inline(name).Width = 120
                d.ok.append(f"inline {name}")
            except Exception as exc:  # noqa: BLE001
                d.failed[f"inline {name}"] = str(exc)[:200]

    d.feature("GIF/BMP/SVG/WEBP inline", formats)

    def floating():
        for wrap, label in ((0, "square"), (1, "tight"), (2, "through"), (4, "top-bottom"), (5, "behind text"), (3, "in front of text")):
            par = d.p(f"Floating picture wrapped {label}. " + "Surrounding text. " * 12)
            shape = doc.Shapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, 20, 5, 60, 60, par.Range)
            shape.WrapFormat.Type = wrap
        par = d.p("Absolutely positioned, rotated picture relative to the page.")
        shape = doc.Shapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, 350, 600, 80, 80, par.Range)
        shape.RelativeHorizontalPosition = 1
        shape.RelativeVerticalPosition = 1
        shape.Rotation = 20
        shape.WrapFormat.Type = 0

    d.feature("floating pictures: square/tight/through/top-bottom/behind/in-front, absolute + rotated", floating)

    def large():
        add_inline("large.jpg").Width = 400

    d.feature("large 4000x3000 JPEG", large)

    def header_logo():
        header = doc.Sections(1).Headers(1)
        header.Range.Text = "Company header with logo "
        at = header.Range
        at.Collapse(0)
        try:
            header.Range.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, at)
        except Exception:  # noqa: BLE001 -- Word inserts the picture, then reports "Command failed"
            pass

    d.feature("picture in header", header_logo)
    d.p("End of images.")
    d.save()


def f05_sections(word):
    d = Doc(word, "a05-sections.docx")
    doc = d.doc
    d.p("Section 1: portrait, different first page", -2)
    d.p("Cover content. " * 20)

    def first_page_header():
        s = doc.Sections(1)
        s.PageSetup.DifferentFirstPageHeaderFooter = True
        s.Headers(2).Range.Text = "FIRST PAGE HEADER"
        s.Headers(1).Range.Text = "Section 1 primary header"
        s.Footers(1).Range.Text = "Section 1 footer"
        s.PageSetup.HeaderDistance = cm(0.8)
        s.PageSetup.FooterDistance = cm(0.6)
        d.p("Second page of section 1. " * 60)

    d.feature("different first page header, custom header/footer distance", first_page_header)

    def landscape_section():
        d.end_range().InsertBreak(2)
        d.first = False
        d.p("Section 2: landscape, own header (not linked)", -2)
        s = doc.Sections(2)
        s.PageSetup.Orientation = 1
        s.Headers(1).LinkToPrevious = False
        s.Headers(1).Range.Text = "Section 2 landscape header"
        s.PageSetup.LeftMargin = cm(3.5)
        d.p("Landscape content. " * 30)

    d.feature("next-page section break, landscape section, unlinked header, different margins", landscape_section)

    def columns_section():
        d.end_range().InsertBreak(3)
        s = doc.Sections(3)
        s.PageSetup.TextColumns.SetCount(2)
        d.p("Section 3: continuous section in two columns", -2)
        d.p("Two-column text. " * 80)

    d.feature("continuous section break with 2 columns", columns_section)

    def restart_numbering():
        d.end_range().InsertBreak(5)
        s = doc.Sections(4)
        s.PageSetup.Orientation = 0
        s.Headers(1).LinkToPrevious = False
        s.Footers(1).LinkToPrevious = False
        pn = s.Footers(1).PageNumbers
        pn.RestartNumberingAtSection = True
        pn.StartingNumber = 1
        pn.NumberStyle = 2  # lowercase roman
        pn.Add(1, True)
        d.p("Section 4: odd-page break, page numbers restart as roman", -2)
        d.p("Appendix text. " * 40)

    d.feature("odd-page section break, page numbering restart (roman)", restart_numbering)

    def odd_even():
        doc.PageSetup.OddAndEvenPagesHeaderFooter = True
        doc.Sections(1).Headers(3).Range.Text = "EVEN PAGE HEADER"

    d.feature("odd/even headers", odd_even)

    def borders_lines_background():
        doc.Sections(1).Borders.Enable = True
        doc.Sections(1).PageSetup.LineNumbering.Active = True
        doc.Background.Fill.ForeColor.RGB = rgb(240, 248, 255)
        doc.Background.Fill.Visible = True
        doc.Background.Fill.Solid()

    d.feature("page borders, line numbering, page background colour", borders_lines_background)

    def watermark():
        header = doc.Sections(1).Headers(1)
        shape = header.Shapes.AddTextEffect(0, "DRAFT", "Arial", 1, False, False, 0, 0)
        shape.Name = "PowerPlusWaterMarkObject1"
        shape.Rotation = 315
        shape.Width = 400
        shape.Height = 100

    d.feature("DRAFT watermark (WordArt in header)", watermark)

    def page_fields():
        f = doc.Sections(2).Footers(1)
        f.LinkToPrevious = False
        f.Range.Text = ""
        rng = f.Range
        rng.Collapse(1)
        rng.InsertAfter("Page ")
        rng.Collapse(0)
        doc.Fields.Add(rng, 33)  # PAGE
        rng = f.Range
        rng.Collapse(0)
        rng.MoveEnd(1, -1)
        rng.InsertAfter(" of ")
        rng.Collapse(0)
        doc.Fields.Add(rng, 26)  # NUMPAGES
        rng = f.Range
        rng.Collapse(0)
        rng.MoveEnd(1, -1)
        rng.InsertAfter(" (section pages: ")
        rng.Collapse(0)
        doc.Fields.Add(rng, 47)  # SECTIONPAGES
        rng = f.Range
        rng.Collapse(0)
        rng.MoveEnd(1, -1)
        rng.InsertAfter(")")

    d.feature("footer with PAGE / NUMPAGES / SECTIONPAGES fields", page_fields)
    d.save()


def f06_fields(word):
    d = Doc(word, "a06-fields.docx")
    doc = d.doc
    doc.BuiltInDocumentProperties("Title").Value = "Fields audit document"
    doc.BuiltInDocumentProperties("Author").Value = "Audit Author"

    def toc():
        par = d.p("")
        doc.TablesOfContents.Add(doc.Range(par.Range.Start, par.Range.Start), True, 1, 3)

    d.feature("TOC field", toc)
    d.p("Chapter one", -2)

    def simple_fields():
        for label, field_type, text in (
            ("Today: ", 31, None),
            ("Now: ", 32, None),
            ("Author: ", 17, None),
            ("Title: ", 15, None),
            ("File name: ", 29, None),
        ):
            par = d.p(label)
            rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
            doc.Fields.Add(rng, field_type)

    d.feature("DATE, TIME, AUTHOR, TITLE, FILENAME fields", simple_fields)

    def bookmarks_refs():
        par = d.p("This sentence holds the bookmarked phrase target phrase here.")
        text = par.Range.Text
        i = text.index("target phrase")
        doc.Bookmarks.Add("AuditTarget", doc.Range(par.Range.Start + i, par.Range.Start + i + len("target phrase")))
        par = d.p("Cross reference to it: ")
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        rng.InsertCrossReference("Bookmark", -1, "AuditTarget", True)
        par = d.p("It is on page ")
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        rng.InsertCrossReference("Bookmark", 7, "AuditTarget", True)

    d.feature("bookmark + REF + PAGEREF cross-references", bookmarks_refs)

    def seq_captions():
        d.p("Chapter two", -2)
        for n in range(2):
            par = d.p("")
            shape = doc.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, doc.Range(par.Range.Start, par.Range.Start))
            d.caption("Figure", f": Figure number {n + 1}")

    d.feature("SEQ Figure captions", seq_captions)

    def styleref():
        header = doc.Sections(1).Headers(1)
        rng = header.Range
        rng.Text = "Chapter: "
        rng = doc.Sections(1).Headers(1).Range
        rng.Collapse(0)
        rng.MoveEnd(1, -1)
        doc.Fields.Add(rng, -1, 'STYLEREF "Heading 1"', False)

    d.feature("STYLEREF in header", styleref)

    def hyperlink_field():
        par = d.p("External hyperlink: ")
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        doc.Hyperlinks.Add(rng, "https://example.com/docs", "", "tooltip", "example documentation")
        par = d.p("Unsafe link: ")
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        doc.Hyperlinks.Add(rng, "file:///C:/secret/local.txt", "", "", "a local file link")

    d.feature("HYPERLINK (https) + file: link", hyperlink_field)

    def citations():
        xml = (
            '<b:Source xmlns:b="http://schemas.openxmlformats.org/officeDocument/2006/bibliography">'
            "<b:Tag>Test2024</b:Tag><b:SourceType>Book</b:SourceType><b:Guid>{A1B2C3D4-0000-0000-0000-000000000001}</b:Guid>"
            "<b:Title>Synthetic Book of Testing</b:Title><b:Year>2024</b:Year>"
            "<b:Author><b:Author><b:NameList><b:Person><b:Last>Tester</b:Last><b:First>Ada</b:First></b:Person></b:NameList></b:Author></b:Author>"
            "</b:Source>"
        )
        doc.Bibliography.Sources.Add(xml)
        par = d.p("A claim with a citation ")
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        doc.Fields.Add(rng, -1, "CITATION Test2024 \\l 1033", False)
        d.p("Bibliography", -2)
        par = d.p("")
        doc.Fields.Add(doc.Range(par.Range.Start, par.Range.Start), -1, "BIBLIOGRAPHY", False)

    d.feature("citation + bibliography", citations)

    def update():
        doc.Fields.Update()
        doc.TablesOfContents(1).Update()

    d.feature("fields updated", update)
    d.save()


def f07_review(word):
    d = Doc(word, "a07-review.docx")
    doc = d.doc
    d.p("Comments and tracked changes", -2)

    def comments():
        par = d.p("This paragraph has a comment on the word important and another on a longer phrase here.")
        text = par.Range.Text
        base = par.Range.Start
        i = text.index("important")
        c1 = doc.Comments.Add(doc.Range(base + i, base + i + len("important")), "Please check this word.")
        c1.Author = "Reviewer A"
        c1.Initial = "RA"
        i = text.index("a longer phrase")
        c2 = doc.Comments.Add(doc.Range(base + i, base + i + len("a longer phrase")), "Second comment, by another reviewer.")
        c2.Author = "Reviewer B"
        c2.Initial = "RB"
        reply = c1.Replies.Add(c1.Scope, "A reply in the thread.")
        reply.Author = "Author C"
        c2.Done = True

    d.feature("comments with ranges, two authors, a reply, a resolved comment", comments)

    def tracked():
        par_ins = d.p("Base sentence for tracked changes.")
        par_del = d.p("This sentence has words to delete here.")
        par_fmt = d.p("This sentence gets a tracked formatting change.")
        par_move = d.p("Paragraph to be moved.")
        d.p("Anchor paragraph for the move.")
        t = d.table(2, 2)
        t.Cell(1, 1).Range.Text = "row one"
        t.Cell(2, 1).Range.Text = "row two"
        doc.TrackRevisions = True
        par_ins = para_with(doc, "Base sentence")
        rng = doc.Range(par_ins.Range.End - 1, par_ins.Range.End - 1)
        rng.InsertAfter(" INSERTED TEXT")
        par_del = para_with(doc, "This sentence has words")
        text = par_del.Range.Text
        i = text.index("words to delete ")
        doc.Range(par_del.Range.Start + i, par_del.Range.Start + i + len("words to delete ")).Delete()
        par_fmt = para_with(doc, "This sentence gets")
        text = par_fmt.Range.Text
        i = text.index("formatting change")
        doc.Range(par_fmt.Range.Start + i, par_fmt.Range.Start + i + len("formatting change")).Font.Bold = True
        para_with(doc, "Paragraph to be moved").Range.Relocate(1)  # move down past the anchor paragraph (no clipboard)
        t.Rows.Add()
        t.Cell(3, 1).Range.Text = "inserted row"
        t.Rows(1).Delete()
        d.p("A whole inserted paragraph.")
        doc.TrackRevisions = False

    d.feature("tracked insertion, deletion, formatting change, move, table row insert/delete, paragraph insert", tracked)
    d.save()


def f08_controls(word):
    d = Doc(word, "a08-content-controls.docx")
    doc = d.doc
    d.p("Content controls and form fields", -2)

    def controls():
        for kind, label in ((1, "Plain text"), (0, "Rich text"), (8, "Checkbox"), (4, "Dropdown"), (3, "Combo box"), (6, "Date picker"), (2, "Picture")):
            par = d.p(f"{label}: ")
            rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
            cc = doc.ContentControls.Add(kind, rng)
            cc.Title = label
            cc.Tag = f"tag-{kind}"
            if kind in (1, 0):
                cc.Range.Text = f"{label} value"
            if kind in (4, 3):
                cc.DropdownListEntries.Add("Option A", "A")
                cc.DropdownListEntries.Add("Option B", "B")
                cc.DropdownListEntries(2).Select()
            if kind == 6:
                cc.DateDisplayFormat = "dd.MM.yyyy"
                cc.Range.Text = "26.09.2026"
            if kind == 8:
                cc.Checked = True
            d.ok.append(f"content control {label}")

    d.feature("content controls: plain/rich/checkbox/dropdown/combo/date/picture", controls)

    def repeating():
        par = d.p("Repeating item text")
        rng = par.Range
        cc = doc.ContentControls.Add(9, doc.Range(rng.Start, rng.End))
        cc.Title = "Repeating section"

    d.feature("repeating section content control", repeating)

    def legacy():
        par = d.p("Legacy form text field: ")
        doc.FormFields.Add(doc.Range(par.Range.End - 1, par.Range.End - 1), 70)
        par = d.p("Legacy form checkbox: ")
        doc.FormFields.Add(doc.Range(par.Range.End - 1, par.Range.End - 1), 71)

    d.feature("legacy FORMTEXT / FORMCHECKBOX", legacy)
    d.save()


def f09_objects(word):
    d = Doc(word, "a09-objects.docx")
    doc = d.doc
    d.p("Text boxes, shapes, SmartArt, charts, OLE, equations, symbols", -2)

    def textbox():
        par = d.p("Paragraph anchoring a text box.")
        box = doc.Shapes.AddTextbox(1, 300, 100, 180, 60, par.Range)
        box.TextFrame.TextRange.Text = "Text inside a text box"

    d.feature("text box", textbox)

    def shape():
        par = d.p("Paragraph anchoring a rectangle shape with text.")
        s = doc.Shapes.AddShape(1, 100, 200, 120, 50, par.Range)
        s.TextFrame.TextRange.Text = "Shape text"

    d.feature("rectangle shape with text", shape)

    def smartart():
        par = d.p("Paragraph anchoring SmartArt.")
        doc.Shapes.AddSmartArt(word.SmartArtLayouts(1), 50, 300, 300, 150, par.Range)

    d.feature("SmartArt", smartart)

    def chart():
        par = d.p("")
        shape = doc.InlineShapes.AddChart2(-1, 51, doc.Range(par.Range.Start, par.Range.Start))
        try:
            shape.Chart.ChartData.Workbook.Close()
        except Exception:  # noqa: BLE001
            pass

    d.feature("chart (clustered column)", chart)

    def ole():
        par = d.p("")
        obj = doc.InlineShapes.AddOLEObject(ClassType="Excel.Sheet.12", Range=doc.Range(par.Range.Start, par.Range.Start))


    d.feature("embedded OLE Excel sheet", ole)

    def equation():
        par = d.p("x=(-b±√(b^2-4ac))/(2a)")
        eq_range = doc.Range(par.Range.Start, par.Range.End - 1)
        eq_range = eq_range.OMaths.Add(eq_range)
        eq_range.OMaths(1).BuildUp()
        par = d.p("Inline equation E=mc^2 inside a sentence.")
        text = par.Range.Text
        i = text.index("E=mc^2")
        inline = doc.Range(par.Range.Start + i, par.Range.Start + i + 6)
        inline = inline.OMaths.Add(inline)
        inline.OMaths(1).BuildUp()

    d.feature("display equation + inline equation (OMML)", equation)

    def symbols():
        par = d.p("Symbols: ")
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        rng.InsertSymbol(74, "Wingdings", True)  # smiley
        rng = doc.Range(par.Range.End - 1, par.Range.End - 1)
        rng.InsertSymbol(0xF0FE - 0x10000, "Wingdings", True)

    d.feature("Wingdings symbols (smiley + checked box)", symbols)

    def drop_cap():
        par = d.p("Once upon a time there was a paragraph with a drop cap letter. " * 3)
        par.DropCap.Position = 1
        par.DropCap.LinesToDrop = 3

    d.feature("drop cap", drop_cap)
    d.save()


def f10_notes(word):
    d = Doc(word, "a10-notes.docx")
    doc = d.doc
    d.p("Footnotes and endnotes", -2)

    def notes():
        for i in range(1, 4):
            par = d.p(f"Sentence {i} with a footnote.")
            fn = doc.Footnotes.Add(doc.Range(par.Range.End - 1, par.Range.End - 1))
            fn.Range.Text = f"Footnote {i} text with bold words"
            r = fn.Range
            words = r.Text.index("bold words")
            fn.Range.Characters(words + 1).Font.Bold = True
            for k in range(words + 1, words + len("bold words") + 1):
                fn.Range.Characters(k).Font.Bold = True
        for i in range(1, 3):
            par = d.p(f"Sentence with endnote {i}.")
            en = doc.Endnotes.Add(doc.Range(par.Range.End - 1, par.Range.End - 1))
            en.Range.Text = f"Endnote {i} text."
        d.p("A long body so the notes land on different pages. " * 120)

    d.feature("3 footnotes (with bold text) + 2 endnotes", notes)
    d.save()


def f11_multilingual(word):
    d = Doc(word, "a11-multilingual.docx")
    doc = d.doc
    d.p("Multilingual document", -2)
    samples = [
        ("English", "The quick brown fox jumps over the lazy dog.", 1033, False),
        ("Bulgarian", "Бързата кафява лисица прескача мързеливото куче.", 1026, False),
        ("German", "Größenmäßig übertrifft die Straße alle Erwartungen.", 1031, False),
        ("Greek", "Η γρήγορη καφέ αλεπού πηδά πάνω από τον τεμπέλη σκύλο.", 1032, False),
        ("Arabic", "الثعلب البني السريع يقفز فوق الكلب الكسول.", 1025, True),
        ("Hebrew", "השועל החום המהיר קופץ מעל הכלב העצלן.", 1037, True),
        ("Chinese", "敏捷的棕色狐狸跳过了懒狗。", 2052, False),
        ("Hindi", "तेज़ भूरी लोमड़ी आलसी कुत्ते के ऊपर कूदती है।", 1081, False),
        ("Emoji", "Status: ✅ done, ⚠️ warning, 🚀 launch.", 1033, False),
    ]

    def add_all():
        for label, text, lang, rtl in samples:
            par = d.p(f"{label}: {text}")
            par.Range.LanguageID = lang
            if rtl:
                par.ReadingOrder = 0
                par.Alignment = 2

    d.feature("en/bg/de/el/ar(RTL)/he(RTL)/zh/hi/emoji paragraphs with language tags", add_all)

    def rtl_table():
        d.p("RTL table:")
        t = d.table(2, 2)
        t.Borders.Enable = True
        t.Cell(1, 1).Range.Text = "عمود ١"
        t.Cell(1, 2).Range.Text = "عمود ٢"
        t.TableDirection = 0

    d.feature("RTL table", rtl_table)
    d.save()


def f12_properties(word):
    d = Doc(word, "a12-properties.docx")
    doc = d.doc

    def props():
        for name, value in (("Title", "Properties audit"), ("Subject", "Metadata"), ("Author", "Audit Author"), ("Keywords", "audit, test"), ("Comments", "Synthetic"), ("Company", "Example Ltd")):
            doc.BuiltInDocumentProperties(name).Value = value
        doc.CustomDocumentProperties.Add("ContractNumber", False, 4, "C-2026-001")
        doc.CustomDocumentProperties.Add("Reviewed", False, 2, True)

    d.feature("core + extended + custom properties", props)

    def custom_xml():
        doc.CustomXMLParts.Add('<audit xmlns="urn:smartdoc:audit"><id>42</id></audit>')

    d.feature("custom XML part", custom_xml)

    def theme():
        base = r"C:\Program Files\Microsoft Office\root\Document Themes 16"
        themes = [f for f in os.listdir(base) if f.endswith(".thmx")] if os.path.isdir(base) else []
        doc.ApplyDocumentTheme(os.path.join(base, themes[0]))
        d.ok.append(f"theme {themes[0]}")

    d.feature("document theme applied", theme)

    def custom_style():
        s = doc.Styles.Add("Audit Custom Style", 1)
        s.Font.Name = "Georgia"
        s.Font.Size = 13
        s.Font.Color = rgb(0, 102, 51)
        s.ParagraphFormat.SpaceAfter = 10
        s.BaseStyle = doc.Styles(-1)
        d.p("Heading styled by the theme's heading font", -2)
        d.p("Body in the theme's body font.")
        d.p("Paragraph in a custom style.", "Audit Custom Style")
        cs = doc.Styles.Add("Audit Char", 2)
        cs.Font.Italic = True
        cs.Font.Color = rgb(153, 0, 0)
        par = d.p("A run in a custom character style here.")
        text = par.Range.Text
        i = text.index("custom character style")
        doc.Range(par.Range.Start + i, par.Range.Start + i + len("custom character style")).Style = cs

    d.feature("custom paragraph + character styles", custom_style)

    def compat():
        doc.Compatibility(8)  # read; keeps compat settings Word writes
        doc.CompatibilityMode  # noqa: B018

    d.feature("compatibility settings present", compat)
    d.save()


def realistic(word):
    # A: university paper
    d = Doc(word, "r01-university-paper.docx")
    doc = d.doc

    def paper():
        d.p("Анализ на форматирането на документи", -63)
        d.p("Курсова работа · Автор: Тест Студентов · 2026").Alignment = 1
        par = d.p("")
        doc.TablesOfContents.Add(doc.Range(par.Range.Start, par.Range.Start), True, 1, 3)
        d.p("Резюме", -2)
        d.p("Тази работа изследва автоматичното форматиране на документи. " * 6).Alignment = 3
        d.p("1. Въведение", -2)
        par = d.p("Форматирането отнема време на студентите [1]. " * 5)
        fn = doc.Footnotes.Add(doc.Range(par.Range.End - 1, par.Range.End - 1))
        fn.Range.Text = "Според проучване на изследователски екип."
        d.p("1.1. Цели", -3)
        pars = [d.p(t) for t in ("Първа цел на изследването", "Втора цел", "Трета цел")]
        doc.Range(pars[0].Range.Start, pars[-1].Range.End).ListFormat.ApplyNumberDefault()
        d.p("2. Методология", -2)
        par = d.p("")
        s = doc.InlineShapes.AddPicture(os.path.join(IMG, "chart.png"), False, True, doc.Range(par.Range.Start, par.Range.Start))
        s.AlternativeText = "Диаграма на резултатите"
        d.caption("Figure", ": Резултати по групи")
        d.p("Таблица с резултати:")
        t = d.table(4, 3)
        t.Style = "Grid Table 4 - Accent 1"
        for r, row in enumerate((("Група", "N", "Среден резултат"), ("А", "24", "4.55"), ("Б", "26", "5.10"), ("В", "22", "4.20")), start=1):
            for c, v in enumerate(row, start=1):
                t.Cell(r, c).Range.Text = v
        d.p("3. Заключение", -2)
        d.p("Автоматизацията спестява време. " * 8).Alignment = 3
        d.p("Литература", -2)
        d.p("[1] Тестов, И. (2025). Форматиране на документи. София: Тест Издат.")
        s = doc.Sections(1)
        f = s.Footers(1)
        doc.Fields.Add(f.Range, 33)
        f.Range.ParagraphFormat.Alignment = 1
        doc.TablesOfContents(1).Update()

    d.feature("university paper: title, TOC, abstract, numbered headings text, footnote, numbered list, figure+caption, styled table, references, page numbers", paper)
    d.save()

    # B: CV
    d = Doc(word, "r02-cv.docx")
    doc = d.doc

    def cv():
        t = doc.Tables.Add(doc.Range(0, 0), 1, 2)
        t.Borders.Enable = False
        t.Columns(1).Width = cm(5)
        t.Columns(2).Width = cm(12)
        doc.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, doc.Range(t.Cell(1, 1).Range.Start, t.Cell(1, 1).Range.Start))
        t.Cell(1, 2).Range.Text = "Тест Тестов\rSoftware Engineer\rtest@example.com · +359 000 000 000"
        t.Cell(1, 2).Range.Paragraphs(1).Range.Font.Size = 20
        t.Cell(1, 2).Range.Paragraphs(1).Range.Font.Bold = True
        d.first = False
        d.p("Experience", -2)
        d.p("2023–now  Senior Tester, Example Ltd")
        pars = [d.p(t) for t in ("Designed audit suites", "Reduced defects by 40%", "Mentored three juniors")]
        doc.Range(pars[0].Range.Start, pars[-1].Range.End).ListFormat.ApplyBulletDefault()
        d.p("Skills", -2)
        t2 = d.table(2, 3)
        t2.Borders.Enable = False
        for r, row in enumerate((("Python", "SQL", "Word"), ("Testing", "Audits", "Docs")), start=1):
            for c, v in enumerate(row, start=1):
                t2.Cell(r, c).Range.Text = v

    d.feature("CV: borderless layout table with photo, bullets, skills grid", cv)
    d.save()

    # C: contract (legal-looking)
    d = Doc(word, "r03-contract.docx")
    doc = d.doc

    def contract():
        d.p("ДОГОВОР ЗА УСЛУГИ № C-2026-001", -63).Alignment = 1
        d.p("Днес, 26.09.2026 г., между страните:").Alignment = 3
        tmpl = doc.ListTemplates.Add(True)
        for level, (style, fmt) in enumerate(((0, "Чл. %1."), (0, "%1.%2."), (4, "(%3)"), (2, "(%4)")), start=1):
            lv = tmpl.ListLevels(level)
            lv.NumberStyle = style
            lv.NumberFormat = fmt
        rows = [(1, "ПРЕДМЕТ НА ДОГОВОРА"), (2, "Изпълнителят се задължава да извърши услугите."), (3, "в срок до 30 дни;"), (3, "с необходимото качество;"), (4, "съгласно Приложение 1."), (2, "Възложителят заплаща възнаграждение."), (1, "СРОК")]
        pars = [d.p(text) for _, text in rows]
        doc.Range(pars[0].Range.Start, pars[-1].Range.End).ListFormat.ApplyListTemplate(tmpl, False, 0)
        for par, (level, _) in zip(pars, rows):
            par.Range.ListFormat.ListLevelNumber = level
            if level == 1:
                par.Range.Font.Bold = True
        par = d.p("„Услуги“ означава дейностите по Приложение 1.")
        par.Range.Words(1).Font.Bold = True
        d.p("Подписи:")
        t = d.table(2, 2)
        t.Borders.Enable = False
        t.Cell(1, 1).Range.Text = "ВЪЗЛОЖИТЕЛ: ____________"
        t.Cell(1, 2).Range.Text = "ИЗПЪЛНИТЕЛ: ____________"
        f = doc.Sections(1).Footers(1)
        f.Range.Text = "Стр. "
        rng = f.Range
        rng.Collapse(0)
        rng.MoveEnd(1, -1)
        doc.Fields.Add(rng, 33)
        rng = f.Range
        rng.Collapse(0)
        rng.MoveEnd(1, -1)
        rng.InsertAfter(" от ")
        rng.Collapse(0)
        doc.Fields.Add(rng, 26)

    d.feature("contract: 'Чл. N.' multilevel numbering (N.N, (a), (i)), bold defined term, signature table, 'Стр. X от Y' footer", contract)
    d.save()

    # D: medical-looking (synthetic)
    d = Doc(word, "r04-medical-synthetic.docx")
    doc = d.doc

    def medical():
        d.p("ЕПИКРИЗА (синтетичен тестов документ)", -63)
        for label, value in (("Пациент:", "Иван Тестов (ИЗМИСЛЕН)"), ("ЕГН:", "0000000000 (фиктивно)"), ("Диагноза:", "J00 Остър назофарингит (тест)")):
            par = d.p(f"{label} {value}")
            doc.Range(par.Range.Start, par.Range.Start + len(label)).Font.Bold = True
        d.p("Лабораторни резултати", -2)
        t = d.table(4, 4)
        t.Borders.Enable = True
        for r, row in enumerate((("Показател", "Стойност", "Единица", "Референтни"), ("Хемоглобин", "140", "g/L", "120–160"), ("Левкоцити", "7.2", "10^9/L", "3.5–10.5"), ("CRP", "12", "mg/L", "< 5")), start=1):
            for c, v in enumerate(row, start=1):
                t.Cell(r, c).Range.Text = v
        t.Rows(1).Range.Font.Bold = True
        t.Cell(4, 2).Range.Font.Color = rgb(192, 0, 0)
        d.p("Терапия: Paracetamol 500 mg 3× дневно.")

    d.feature("medical-looking synthetic: bold labels, lab table with red out-of-range value", medical)
    d.save()

    # E: invoice
    d = Doc(word, "r05-invoice.docx")
    doc = d.doc

    def invoice():
        header = doc.Sections(1).Headers(1)
        header.Range.Text = "Example Ltd "
        at = header.Range
        at.Collapse(0)
        try:
            header.Range.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, at)
        except Exception:  # noqa: BLE001 -- Word inserts the picture, then reports "Command failed"
            pass
        d.p("ФАКТУРА № 0000000001", -63)
        d.p("Дата: 26.09.2026 · Доставчик: Example Ltd · ЕИК 000000000")
        t = d.table(5, 4)
        t.Style = "Grid Table 1 Light"
        for r, row in enumerate((("Описание", "Кол.", "Ед. цена", "Сума"), ("Услуга А", "2", "100.00", "200.00"), ("Услуга Б", "1", "50.00", "50.00"), ("", "", "ДДС 20%", "50.00"), ("", "", "ОБЩО", "300.00")), start=1):
            for c, v in enumerate(row, start=1):
                t.Cell(r, c).Range.Text = v
                if c > 1:
                    t.Cell(r, c).Range.ParagraphFormat.Alignment = 2
        t.Rows(5).Range.Font.Bold = True
        t.Cell(5, 1).Merge(t.Cell(5, 3))

    d.feature("invoice: header logo, right-aligned numbers, merged total row, table style", invoice)
    d.save()


def f13_pictures(word):
    """Pictures as Word writes them (DOCX-018, DOCX-027): cropped, turned and flipped,
    floating with text around it, in a numbered list's items, in a table cell."""
    d = Doc(word, "a13-pictures.docx")
    doc = d.doc
    d.p("Pictures as Word writes them", -2)

    def cropped():
        par = d.p("")
        shape = doc.InlineShapes.AddPicture(os.path.join(IMG, "chart.png"), False, True, doc.Range(par.Range.Start, par.Range.Start))
        shape.Width = cm(8)
        shape.PictureFormat.CropLeft = cm(2)
        shape.AlternativeText = "A chart cropped on the left"

    d.feature("inline picture cropped on the left, with alt text", cropped)

    def turned():
        par = d.p("")
        inline = doc.InlineShapes.AddPicture(os.path.join(IMG, "photo.jpg"), False, True, doc.Range(par.Range.Start, par.Range.Start))
        inline.Width = cm(5)
        shape = inline.ConvertToShape()
        shape.Rotation = 90
        shape.Flip(0)  # msoFlipHorizontal
        shape.ConvertToInlineShape()

    d.feature("inline picture turned a quarter and flipped", turned)

    def floating():
        d.p("Text flows around the picture placed 2 cm from the margin. " * 6)
        anchor = d.p("The paragraph the floating picture is anchored to.")
        shape = doc.Shapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, cm(2), 0, cm(3), cm(3), doc.Range(anchor.Range.Start, anchor.Range.Start))
        shape.WrapFormat.Type = 0  # wdWrapSquare
        shape.RelativeHorizontalPosition = 0  # the margin
        shape.RelativeVerticalPosition = 2  # the paragraph
        shape.Left = cm(2)
        shape.Top = 0

    d.feature("floating picture, square wrap, 2 cm from the margin", floating)

    def in_list():
        pars = [d.p(text) for text in ("Open the box", "", "Close it")]
        doc.Range(pars[0].Range.Start, pars[-1].Range.End).ListFormat.ApplyNumberDefault()
        for par in pars[:2]:
            end = par.Range.End - 1
            doc.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, doc.Range(end, end)).Width = cm(1.5)

    d.feature("pictures in numbered list items, one item only its picture", in_list)

    def in_cell():
        t = d.table(1, 2)
        t.Borders.Enable = True
        t.Cell(1, 1).Range.Text = "A picture in a cell:"
        end = t.Cell(1, 1).Range.End - 1
        doc.InlineShapes.AddPicture(os.path.join(IMG, "logo.png"), False, True, doc.Range(end, end)).Width = cm(3)
        t.Cell(1, 2).Range.Text = "Beside it."

    d.feature("picture in a table cell", in_cell)
    d.save()


def f14_styles(word):
    """Word's styles changed (FMT-004): a heading that isn't bold and has no spacing,
    body text with none either, a quote without an indent, a caption that isn't
    italic -- what an import must keep instead of the app's defaults."""
    d = Doc(word, "a14-modified-styles.docx")
    doc = d.doc

    def styles():
        heading = doc.Styles(-2)  # Heading 1
        heading.Font.Bold = False
        heading.Font.Size = 18
        heading.ParagraphFormat.SpaceBefore = 0
        heading.ParagraphFormat.SpaceAfter = 0
        normal = doc.Styles(-1)
        normal.ParagraphFormat.SpaceAfter = 0
        normal.ParagraphFormat.LineSpacingRule = 0  # single
        quote = doc.Styles(-181)  # Quote
        quote.ParagraphFormat.LeftIndent = 0
        quote.ParagraphFormat.RightIndent = 0
        quote.ParagraphFormat.Alignment = 0
        doc.Styles(-35).Font.Italic = False  # Caption

    d.feature("Heading 1 regular 18 pt with no spacing; Normal single-spaced with none; Quote not indented; Caption not italic", styles)

    def content():
        d.p("A heading that isn't bold", -2)
        d.p("Body text with no space after it. " * 4)
        d.p("A quotation without an indent.", -181)
        t = d.table(2, 2)
        t.Borders.Enable = True
        for r, row in enumerate((("Item", "Value"), ("A", "1")), start=1):
            for c, v in enumerate(row, start=1):
                t.Cell(r, c).Range.Text = v
        d.p("A paragraph right after the table.")
        d.caption("Table", ": A caption that isn't italic")

    d.feature("heading, body, quote, a table followed by text, caption", content)
    d.save()


def f15_links(word):
    """Links as Word writes them (DOCX-026): a web link with a ScreenTip, a mail link,
    addresses typed as plain text (not links), a bookmark with a link and a
    cross-reference to it."""
    d = Doc(word, "a15-links.docx")
    doc = d.doc
    d.p("Links", -2)

    def web_and_mail():
        par = d.p("Read the documentation or write to us.")
        text = par.Range.Text
        # The later one first: a link added changes the positions after it.
        for word_text, address, tip in (("write to us", "mailto:team@example.org", ""), ("the documentation", "https://example.com/docs", "Opens the docs")):
            i = text.index(word_text)
            doc.Hyperlinks.Add(doc.Range(par.Range.Start + i, par.Range.Start + i + len(word_text)), address, "", tip, word_text)

    d.feature("hyperlinks: web with a ScreenTip, mailto", web_and_mail)

    def plain():
        d.p("Typed as plain text, not links: www.example.net and someone@example.com.")

    d.feature("plain-text web and e-mail addresses (not links)", plain)

    def bookmark_and_reference():
        target = d.p("The results")
        doc.Bookmarks.Add("Results", d.text_range(target))
        par = d.p("See the results: ")
        end = par.Range.End - 1
        doc.Hyperlinks.Add(doc.Range(end, end), "", "Results", "", "the results above")
        par = d.p("They are on page ")
        end = par.Range.End - 1
        doc.Fields.Add(doc.Range(end, end), -1, "PAGEREF Results " + chr(92) + "h", False)

    d.feature("bookmark, an internal link to it, a PAGEREF cross-reference", bookmark_and_reference)
    d.save()


BUILDERS = [
    f01_formatting, f02_tables, f03_lists, f04_images, f05_sections, f06_fields, f07_review, f08_controls, f09_objects,
    f10_notes, f11_multilingual, f12_properties, f13_pictures, f14_styles, f15_links, realistic,
]


def _pids(image: str) -> set[str]:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return {line.split('","')[1] for line in out.splitlines() if line.startswith(f'"{image}"')}


# The fixtures' own made-up values, which stay (a12 and a07 set them on purpose).
SYNTHETIC_COMPANIES = {"", "Example Ltd"}
SYNTHETIC_AUTHORS = {"Word User", "Audit Author"}
SYNTHETIC_PEOPLE = {"Word User", "Reviewer A", "Reviewer B", "Author C", "Audit Author", "RA", "RB", "AC", "WU"}

# Who wrote a comment or a change, by name and by initials: Word may use the signed-in
# account's display name there rather than its own user name.
_PERSON = re.compile(r'(w(?:15)?:author|w:initials)="([^"]*)"')

_MSIP_PROPERTY = re.compile(r"<property\b[^>]*\bname=\"MSIP_Label_[^\"]*\"[^>]*>.*?</property>", re.S)
_PRESENCE = re.compile(r"<w15:presenceInfo\b[^>]*/>")
_COMPANY = re.compile(r"<Company>([^<]*)</Company>")
_MANAGER = re.compile(r"<Manager>[^<]*</Manager>|<Manager/>")
_CORE_PEOPLE = re.compile(r"<(dc:creator|cp:lastModifiedBy)>([^<]*)</\1>")


def scrub_text(name: str, text: str, user: list[str]) -> str:
    """One package part without what would identify the machine or its user: the Word
    user's name and initials, the sensitivity labels Office stamps with the
    organisation's tenant (MSIP_Label_*), comment authors' sign-in identities
    (w15:presenceInfo), a company or manager or author Office filled in."""
    full_name, initials = (user + ["", ""])[:2]
    if full_name and len(full_name) >= 4:
        text = text.replace(full_name, "Word User")
    if initials:
        text = re.sub(f'(?<=w:initials="){re.escape(initials)}(?=")', "WU", text)
    text = _PERSON.sub(
        lambda m: m.group(0) if m.group(2) in SYNTHETIC_PEOPLE else f'{m.group(1)}="{"WU" if m.group(1) == "w:initials" else "Word User"}"',
        text,
    )
    if name == "docProps/custom.xml":
        text = _MSIP_PROPERTY.sub("", text)
    if name == "word/people.xml":
        text = _PRESENCE.sub("", text)
    if name == "docProps/app.xml":
        text = _COMPANY.sub(lambda m: m.group(0) if m.group(1) in SYNTHETIC_COMPANIES else "<Company></Company>", text)
        text = _MANAGER.sub("", text)
    if name == "docProps/core.xml":
        text = _CORE_PEOPLE.sub(lambda m: m.group(0) if m.group(2) in SYNTHETIC_AUTHORS else f"<{m.group(1)}>Word User</{m.group(1)}>", text)
    return text


def scrub(path: str, user: list[str]) -> None:
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith((".xml", ".rels")):
                data = scrub_text(info.filename, data.decode("utf-8"), user).encode("utf-8")
            dst.writestr(info, data)
    shutil.move(tmp, path)


def main():
    if _pids("WINWORD.EXE"):
        sys.exit("Word is already running - refusing to automate it")
    os.makedirs(FIX, exist_ok=True)
    make_images()
    only = set(sys.argv[1:])
    word = win32.DispatchEx("Word.Application")
    user = [word.UserName, word.UserInitials]
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        for builder in BUILDERS:
            if only and builder.__name__ not in only:
                continue
            try:
                builder(word)
            except Exception:  # noqa: BLE001
                print(f"{builder.__name__} FAILED\n{traceback.format_exc()}")
                for doc in list(word.Documents):
                    doc.Close(False)
    finally:
        word.Quit()  # the Excel an embedded chart or sheet started closes with it; nothing is killed
        shutil.rmtree(IMG, ignore_errors=True)
    for name in MANIFEST:
        scrub(os.path.join(FIX, name), user)
    path = os.path.join(FIX, "manifest.json")
    existing = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    existing.update(MANIFEST)
    with open(path, "w", encoding="utf-8") as out:
        json.dump(dict(sorted(existing.items())), out, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
