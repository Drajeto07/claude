from app.parsers.detection import looks_like_markdown


def test_plain_prose_is_not_markdown():
    text = "This is a perfectly ordinary paragraph. It has sentences. Nothing special here."
    assert looks_like_markdown(text) is False


def test_spec_example_numbered_short_line_is_not_markdown():
    # Spec Section 7.4's own example: a short numbered line followed by a
    # longer paragraph must be handled by AI heuristics, not treated as
    # Markdown just because it superficially resembles a list item.
    text = "1. Въведение\n\nТова е доста по-дълъг параграф, който следва краткия ред отгоре."
    assert looks_like_markdown(text) is False


def test_lone_list_marker_is_not_markdown():
    text = "- just one bullet point in the middle of otherwise plain prose"
    assert looks_like_markdown(text) is False


def test_stray_asterisk_is_not_markdown():
    text = "The result was 5 * 3 = 15, which surprised everyone in the room."
    assert looks_like_markdown(text) is False


def test_atx_heading_alone_is_markdown():
    assert looks_like_markdown("# A Heading\n\nSome text.") is True


def test_fenced_code_block_alone_is_markdown():
    assert looks_like_markdown("Some text\n\n```\ncode here\n```\n") is True


def test_table_delimiter_row_alone_is_markdown():
    text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    assert looks_like_markdown(text) is True


def test_two_moderate_signals_together_is_markdown():
    text = "This has **bold text** and also a [link](https://example.com) in it."
    assert looks_like_markdown(text) is True


def test_single_moderate_signal_is_not_enough():
    text = "This has **bold text** but nothing else that looks like markdown."
    assert looks_like_markdown(text) is False
