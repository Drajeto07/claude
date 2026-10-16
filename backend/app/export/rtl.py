"""Right-to-left paragraphs in the PDF (tracker FONT-003). reportlab 5.0.1 orders a line's words
right to left only for a paragraph of one font and no shaping: its other path, the one shaping
and mixed fonts take, leaves bidi off. So a paragraph led by right-to-left text is laid out here:

  1. reportlab breaks it into lines in logical order, shaped, so each line's width is exact;
  2. each line's words are put in the order they are seen (app/bidi.py, word by word: a word
     keeps its runs, so its formatting, and HarfBuzz has already put its letters right to left);
  3. each line is drawn as a paragraph of one line, aligned as the paragraph is -- to the right
     unless set otherwise; a justified paragraph's lines but the last are justified.

The flowable splits between its lines across pages and columns."""

import copy
import re
from collections.abc import Callable

from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.textobject import bidiWordList
from reportlab.platypus import Flowable, Paragraph

from app.models.document import InlineRun

Markup = Callable[[list[InlineRun]], str]
_SPACE = re.compile(r"(\s+)")


def words_of(runs: list[InlineRun]) -> list[list[InlineRun]]:
    """The runs cut into words, each word the pieces of the runs it is made of."""
    words: list[list[InlineRun]] = [[]]
    for run in runs:
        for part in _SPACE.split(run.text):
            if not part:
                continue
            if part.isspace():
                if words[-1]:
                    words.append([])
                continue
            words[-1].append(InlineRun(text=part, marks=run.marks))
    return [word for word in words if word]


def _line_word_counts(lines) -> list[int]:
    counts = []
    for line in lines:
        if isinstance(line, tuple):  # a plain paragraph's line: (extra space, words)
            counts.append(len(line[1]))
        else:  # a mixed one's: frags whose text holds its words
            text = " ".join(str(getattr(frag, "text", "")) for frag in getattr(line, "words", []))
            counts.append(len(text.split()))
    return counts


class RtlParagraph(Flowable):
    def __init__(self, runs: list[InlineRun], style: ParagraphStyle, markup: Markup, *, explicit_alignment: bool) -> None:
        super().__init__()
        self._words = words_of(runs)
        self._style = style
        self._markup = markup
        self._explicit = explicit_alignment
        self._lines: list[Paragraph] = []
        self._heights: list[float] = []

    def _logical(self) -> Paragraph:
        style = copy.copy(self._style)
        style.wordWrap = None
        return Paragraph(" ".join(self._markup(word) for word in self._words) or "&nbsp;", style)

    def _build(self, width: float) -> None:
        measured = self._logical()
        measured.wrap(width, 1e9)
        counts = _line_word_counts(measured.blPara.lines) if getattr(measured, "blPara", None) else [len(self._words)]
        if sum(counts) != len(self._words):  # can't be told apart: one line per paragraph, wrapped as reportlab can
            counts = [len(self._words)]
        lines: list[Paragraph] = []
        start = 0
        for index, count in enumerate(counts):
            line_words = self._words[start : start + count]
            start += count
            texts = ["".join(piece.text for piece in word) for word in line_words]
            visual = bidiWordList(texts, direction="RTL", wx=True) if texts else []
            ordered = [word for _, word in sorted(zip(visual, line_words, strict=True), key=lambda pair: pair[0])]
            last = index == len(counts) - 1
            style = copy.copy(self._style)
            style.wordWrap = None
            if not self._explicit:
                style.alignment = TA_RIGHT
            elif self._style.alignment == TA_JUSTIFY and last:
                style.alignment = TA_RIGHT
            if index:
                style.spaceBefore = 0
                style.firstLineIndent = 0
            elif style.firstLineIndent:  # a first-line indent is on the right of a right-to-left paragraph
                style.rightIndent += style.firstLineIndent
                style.firstLineIndent = 0
            if not last:
                style.spaceAfter = 0
            lines.append(Paragraph(" ".join(self._markup(word) for word in ordered) or "&nbsp;", style))
        self._lines = lines

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self._build(availWidth)
        self._heights = [line.wrap(availWidth, availHeight)[1] for line in self._lines]
        self.width = availWidth
        self.height = sum(self._heights)
        return availWidth, self.height

    def getSpaceBefore(self) -> float:
        return self._style.spaceBefore

    def getSpaceAfter(self) -> float:
        return self._style.spaceAfter

    def split(self, availWidth: float, availHeight: float) -> list[Flowable]:
        self.wrap(availWidth, availHeight)
        return list(self._lines) if len(self._lines) > 1 else []

    def draw(self) -> None:
        y = self.height
        for line, height in zip(self._lines, self._heights, strict=True):
            y -= height
            line.drawOn(self.canv, 0, y)
