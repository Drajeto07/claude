from app.models.document import ElementType, MarkType
from app.parsers.markdown import parse_markdown

# Modeled on the real ChatGPT-generated Markdown document that exposed the
# naive segmenter's limitations and triggered this whole phase of work.
SAMPLE = """# Автоматично форматиране на текст

## 1. Основен текст

Ето и малко **удебелен текст**, малко *курсивен текст*. Можем да добавим и `inline code`.

### 1.1 Малко подзаглавие

Текст под подзаглавие.

## 2. Списъци

* Първи елемент
* Втори елемент

  * Подточка

1. Отвори документа.
2. Провери съдържанието.

* [x] Свършена задача
* [ ] Незавършена задача

## 3. Цитат

> Това е примерен цитат.

## 4. Код

```python
def hello():
    return "world"
```

## 5. Таблица

| Име | Цена |
| --- | ---: |
| Мишка | 49.50 |

[Линк](https://example.com) в текста.
"""


def test_first_heading_becomes_level_1_and_document_title():
    document = parse_markdown(SAMPLE)
    heading = document.elements[0]
    assert heading.type == ElementType.HEADING
    assert heading.level == 1
    assert heading.content == "Автоматично форматиране на текст"
    assert document.metadata.title == "Автоматично форматиране на текст"


def test_heading_levels_are_preserved():
    headings = {e.content: e.level for e in _elements(ElementType.HEADING)}
    assert headings["1. Основен текст"] == 2
    assert headings["1.1 Малко подзаглавие"] == 3


def test_inline_marks_are_extracted():
    paragraph = next(e for e in _elements(ElementType.PARAGRAPH) if "удебелен" in e.content)
    marked = {frozenset(m.type for m in run.marks): run.text for run in paragraph.inline}
    assert any(MarkType.BOLD in marks for marks, text in marked.items() if "удебелен текст" in text)
    assert any(MarkType.ITALIC in marks for marks, text in marked.items() if "курсивен текст" in text)
    assert any(MarkType.CODE in marks for marks, text in marked.items() if "inline code" in text)


def test_lists_capture_items_ordering_and_nesting():
    document = parse_markdown(SAMPLE)
    lists = [e for e in document.elements if e.type == ElementType.LIST]
    bullet_list = lists[0]
    assert bullet_list.ordered is False
    assert [item.level for item in bullet_list.listItems] == [0, 0, 1]

    ordered_list = lists[1]
    assert ordered_list.ordered is True
    assert len(ordered_list.listItems) == 2


def test_checklist_items_capture_checked_state():
    document = parse_markdown(SAMPLE)
    lists = [e for e in document.elements if e.type == ElementType.LIST]
    checklist = lists[2]
    assert [item.checked for item in checklist.listItems] == [True, False]
    # the literal "[x] "/"[ ] " markup must not leak into the item text
    assert all("[" not in item.inline[0].text for item in checklist.listItems)


def test_blockquote_becomes_quote_element():
    quote = _elements(ElementType.QUOTE)[0]
    assert quote.content == "Това е примерен цитат."


def test_fenced_code_block_captures_language_and_body():
    code = _elements(ElementType.CODE_BLOCK)[0]
    assert code.language == "python"
    assert 'return "world"' in code.content


def test_table_captures_alignment_header_and_cells():
    table = _elements(ElementType.TABLE)[0].table
    assert table.hasHeaderRow is True
    # Plain "---" (no colon) means "unspecified" per GFM, not "left" --
    # only ":---"/"---:"/":---:" register an explicit alignment.
    assert table.alignments == [None, "right"]
    assert table.rows[0].cells[0].header is True
    body_row = table.rows[1]
    assert [c.inline[0].text for c in body_row.cells] == ["Мишка", "49.50"]


def test_link_mark_carries_href():
    paragraph = next(e for e in _elements(ElementType.PARAGRAPH) if "Линк" in e.content)
    link_run = next(run for run in paragraph.inline if any(m.type == MarkType.LINK for m in run.marks))
    link_mark = next(m for m in link_run.marks if m.type == MarkType.LINK)
    assert link_mark.href == "https://example.com"


def test_all_elements_have_full_confidence():
    document = parse_markdown(SAMPLE)
    assert all(e.confidence == 1.0 for e in document.elements)


def _elements(element_type: ElementType):
    return [e for e in parse_markdown(SAMPLE).elements if e.type == element_type]
