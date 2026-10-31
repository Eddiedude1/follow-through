import pytest

from follow_through import agent, bot, config, db
from tests.conftest import FakeChat, FakeContext, FakeUpdate, _FakeCallbackUpdate, FakeCallbackQuery


def _callback_datas(markup):
    return {button.callback_data for row in markup.inline_keyboard for button in row}


@pytest.mark.asyncio
async def test_handle_open_lists_open_commitments(tmp_db_conn, fake_update, fake_context):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    db.insert_commitment(tmp_db_conn, note_id, "organize the garage", "2026-11-02")
    await bot.handle_open(fake_update, fake_context)
    assert "organize the garage" in fake_update.message.replies[0]


@pytest.mark.asyncio
async def test_dismiss_button_calls_dismiss_commitment_directly(tmp_db_conn, fake_callback_query):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    fake_callback_query.data = f"dismiss:{cid}"
    await bot.handle_button(fake_callback_query.update, fake_callback_query.context)
    assert db.list_open_commitments(tmp_db_conn) == []


@pytest.mark.asyncio
async def test_week_appends_proactive_suggestion(tmp_db_conn, fake_update, fake_context, monkeypatch):
    monkeypatch.setattr(agent, "get_proactive_suggestion", lambda conn, client: "Take dinner off her plate tonight.")
    await bot.handle_week(fake_update, fake_context)
    assert "Take dinner off her plate tonight." in fake_update.message.replies[-1]


@pytest.mark.asyncio
async def test_handle_open_ignores_messages_from_other_chats(tmp_db_conn):
    # Final review Critical #3: no chat filter means any Telegram user who
    # finds the bot could read private notes about someone's wife.
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    db.insert_commitment(tmp_db_conn, note_id, "organize the garage", "2026-11-02")

    update = FakeUpdate()
    update.effective_chat = FakeChat(id=999)
    context = FakeContext(conn=tmp_db_conn)

    await bot.handle_open(update, context)
    assert update.message.replies == []


@pytest.mark.asyncio
async def test_handle_button_ignores_callbacks_from_other_chats(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")

    query = FakeCallbackQuery()
    query.data = f"dismiss:{cid}"
    query.update = _FakeCallbackUpdate(query)
    query.update.effective_chat = FakeChat(id=999)
    query.context = FakeContext(conn=tmp_db_conn)

    await bot.handle_button(query.update, query.context)
    assert db.list_open_commitments(tmp_db_conn) != []


@pytest.mark.asyncio
async def test_handle_open_includes_done_and_dismiss_buttons(tmp_db_conn, fake_update, fake_context):
    # Final review Important #5: after Confirm (or on /open), there was no
    # Done button anywhere, so the Close step of the core loop was
    # unreachable on the happy path.
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "organize the garage", "2026-11-02")
    await bot.handle_open(fake_update, fake_context)
    markup = fake_update.message.markups[0]
    assert markup is not None
    datas = _callback_datas(markup)
    assert f"done:{cid}" in datas
    assert f"dismiss:{cid}" in datas


@pytest.mark.asyncio
async def test_confirm_button_keeps_done_button(tmp_db_conn, fake_callback_query):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    fake_callback_query.data = f"confirm:{cid}"
    await bot.handle_button(fake_callback_query.update, fake_callback_query.context)
    markup = fake_callback_query.message.markups[-1]
    assert markup is not None
    assert f"done:{cid}" in _callback_datas(markup)


@pytest.mark.asyncio
async def test_edit_due_rejects_invalid_date_and_reprompts(tmp_db_conn, fake_context):
    # Final review Important #6: free text like "friday" was stored
    # verbatim; since due dates are compared as strings, that drops the
    # item out of /week forever with no error shown.
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    fake_context.user_data["pending_edit_due"] = cid

    update = FakeUpdate(text="friday")
    await bot.handle_message(update, fake_context)

    assert db.list_open_commitments(tmp_db_conn)[0]["due"] == "2026-11-02"
    assert fake_context.user_data["pending_edit_due"] == cid
    assert "YYYY-MM-DD" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_edit_due_moves_existing_reminder_to_new_date(tmp_db_conn, fake_context):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "text")
    fake_context.user_data["pending_edit_due"] = cid

    update = FakeUpdate(text="2026-11-05")
    await bot.handle_message(update, fake_context)

    assert db.list_open_commitments(tmp_db_conn)[0]["due"] == "2026-11-05"
    reminder = db.get_unsent_reminder_for_commitment(tmp_db_conn, cid)
    assert reminder["when_ts"] == "2026-11-05T09:00:00"
    assert "pending_edit_due" not in fake_context.user_data


def test_build_app_initializes_schema_on_a_fresh_db(tmp_path, monkeypatch):
    # Final review Critical #2: production entry points never called
    # init_schema, so a fresh Pi fails on its first message with
    # "no such table".
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "fresh.db"))
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123456:FAKE-TOKEN-FOR-TEST")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake-key-for-test")
    app = bot.build_app()
    conn = app.bot_data["conn"]
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"notes", "commitments", "reminders"} <= tables


def test_build_app_registers_an_error_handler(tmp_path, monkeypatch):
    # Final review Important #7: no error handler meant any exception in a
    # handler (including Critical #1's missing max_tokens) was invisible
    # to the user — the bot would just silently never reply.
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "fresh.db"))
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123456:FAKE-TOKEN-FOR-TEST")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake-key-for-test")
    app = bot.build_app()
    assert len(app.error_handlers) > 0
