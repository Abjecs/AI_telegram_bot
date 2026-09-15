from services.gigachat import _build_messages, _extract_text


def test_build_messages_preserves_system_history_and_user_message():
    messages = _build_messages(
        "system prompt",
        "current question",
        [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ],
    )

    assert [message.role for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[0].content == "system prompt"
    assert messages[-1].content == "current question"


def test_extract_text_from_current_completion_response():
    class Part:
        text = "hello"

    class Message:
        content = [Part()]

    class Response:
        messages = [Message()]

    assert _extract_text(Response()) == "hello"


def test_extract_text_from_legacy_completion_response():
    class Message:
        content = "legacy hello"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    assert _extract_text(Response()) == "legacy hello"
