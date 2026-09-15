from services.text import split_text


def test_split_text_keeps_all_content():
    text = "A" * 9000
    chunks = split_text(text, limit=4096)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 4096 for chunk in chunks)


def test_split_text_prefers_word_boundaries():
    text = "слово " * 1000
    chunks = split_text(text, limit=100)
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert " ".join(chunks) == text.strip()
