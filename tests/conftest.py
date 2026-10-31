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


class FakeTelegramMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)


class FakeChat:
    def __init__(self, id=1):
        self.id = id


class FakeUpdate:
    def __init__(self, text=""):
        self.message = FakeTelegramMessage(text)
        self.effective_chat = FakeChat()
        self.callback_query = None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


class FakeContext:
    def __init__(self, conn=None, client=None):
        self.bot_data = {}
        if conn is not None:
            self.bot_data["conn"] = conn
        if client is not None:
            self.bot_data["client"] = client
        self.bot = FakeBot()
        self.user_data = {}


@pytest.fixture
def fake_update():
    return FakeUpdate()


@pytest.fixture
def fake_context(tmp_db_conn):
    return FakeContext(conn=tmp_db_conn)


class FakeCallbackQuery:
    def __init__(self, data=""):
        self.data = data
        self.message = FakeTelegramMessage()

    async def answer(self):
        pass

    async def edit_message_text(self, text, reply_markup=None):
        self.message.replies.append(text)


class _FakeCallbackUpdate:
    def __init__(self, callback_query):
        self.callback_query = callback_query
        self.effective_chat = FakeChat()


@pytest.fixture
def fake_callback_query(tmp_db_conn):
    query = FakeCallbackQuery()
    query.update = _FakeCallbackUpdate(query)
    query.context = FakeContext(conn=tmp_db_conn)
    return query
