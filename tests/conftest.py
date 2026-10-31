import itertools

import pytest

from follow_through import db


@pytest.fixture
def tmp_db_conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    yield conn
    conn.close()


class FakeContentBlock:
    def __init__(self, type, **kwargs):
        self.type = type
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeMessage:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


_tool_use_id_counter = itertools.count(1)


def fake_text_response(text):
    return FakeMessage("end_turn", [FakeContentBlock("text", text=text)])


def fake_tool_use_response(name, input):
    tool_use_id = f"toolu_{next(_tool_use_id_counter)}"
    return FakeMessage(
        "tool_use", [FakeContentBlock("tool_use", id=tool_use_id, name=name, input=input)]
    )


class FakeAnthropicClient:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            try:
                return next(self._outer._responses)
            except StopIteration:
                raise AssertionError("FakeAnthropicClient ran out of scripted responses")
