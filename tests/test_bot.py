import pytest

from follow_through import agent, bot, db


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
