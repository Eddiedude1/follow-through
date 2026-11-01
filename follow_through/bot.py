import asyncio
from datetime import date, datetime, timedelta, timezone

import anthropic
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from follow_through import agent, config, db


def _is_authorized_chat(chat_id) -> bool:
    configured = config.TELEGRAM_CHAT_ID
    if not configured:
        return False
    return str(chat_id) == str(configured)


def _reply_text_or_fallback(text: str) -> str:
    return text if text and text.strip() else "(no response text)"


def _build_commitment_keyboard(commitment_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("Confirm", callback_data=f"confirm:{commitment_id}"),
        InlineKeyboardButton("Edit due date", callback_data=f"edit_due:{commitment_id}"),
        InlineKeyboardButton("Dismiss", callback_data=f"dismiss:{commitment_id}"),
        InlineKeyboardButton("Done", callback_data=f"done:{commitment_id}"),
    ]
    return InlineKeyboardMarkup([buttons])


def _build_done_dismiss_keyboard(commitment_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("Edit due date", callback_data=f"edit_due:{commitment_id}"),
        InlineKeyboardButton("Dismiss", callback_data=f"dismiss:{commitment_id}"),
        InlineKeyboardButton("Done", callback_data=f"done:{commitment_id}"),
    ]
    return InlineKeyboardMarkup([buttons])


async def handle_done_reply(update, context) -> None:
    conn = context.bot_data["conn"]
    client = context.bot_data["client"]
    commitment_id = context.user_data.pop("pending_done")
    reaction_text = update.message.text

    message = (
        f"Commitment id {commitment_id} is done. "
        f"Her reaction: {reaction_text}. Call mark_done for it."
    )
    result = await asyncio.to_thread(agent.run_agent, conn, message, client)
    await update.message.reply_text(_reply_text_or_fallback(result.final_text))


async def handle_message(update, context) -> None:
    if not _is_authorized_chat(update.effective_chat.id):
        return

    conn = context.bot_data["conn"]

    if "pending_edit_due" in context.user_data:
        commitment_id = context.user_data["pending_edit_due"]
        new_due_text = update.message.text.strip()
        try:
            new_due = date.fromisoformat(new_due_text)
        except ValueError:
            await update.message.reply_text(
                "That doesn't look like a date. Please use YYYY-MM-DD."
            )
            return

        context.user_data.pop("pending_edit_due")
        db.update_commitment_due(conn, commitment_id, new_due.isoformat())

        reminder = db.get_unsent_reminder_for_commitment(conn, commitment_id)
        if reminder is not None:
            old_when = datetime.fromisoformat(reminder["when_ts"])
            new_when = old_when.replace(year=new_due.year, month=new_due.month, day=new_due.day)
            db.update_reminder_when(conn, reminder["id"], new_when.isoformat())

        await update.message.reply_text("Due date updated.")
        return

    if "pending_done" in context.user_data:
        await handle_done_reply(update, context)
        return

    client = context.bot_data["client"]
    before_ids = {c["id"] for c in db.list_open_commitments(conn)}
    result = await asyncio.to_thread(agent.run_agent, conn, update.message.text, client)
    after = db.list_open_commitments(conn)
    new_commitments = [c for c in after if c["id"] not in before_ids]

    await update.message.reply_text(_reply_text_or_fallback(result.final_text))
    for commitment in new_commitments:
        await update.message.reply_text(
            f"{commitment['act']} — due {commitment['due']}",
            reply_markup=_build_commitment_keyboard(commitment["id"]),
        )


async def handle_open(update, context) -> None:
    if not _is_authorized_chat(update.effective_chat.id):
        return

    conn = context.bot_data["conn"]
    commitments = db.list_open_commitments(conn)
    if not commitments:
        await update.message.reply_text("Nothing open right now.")
        return
    for commitment in commitments:
        await update.message.reply_text(
            f"- {commitment['act']} (due {commitment['due']})",
            reply_markup=_build_done_dismiss_keyboard(commitment["id"]),
        )


async def handle_week(update, context) -> None:
    if not _is_authorized_chat(update.effective_chat.id):
        return

    conn = context.bot_data["conn"]
    client = context.bot_data.get("client")

    cutoff = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    due_this_week = [c for c in db.list_open_commitments(conn) if c["due"] <= cutoff]

    if due_this_week:
        lines = [f"- {c['act']} (due {c['due']})" for c in due_this_week]
        await update.message.reply_text("Due this week:\n" + "\n".join(lines))
    else:
        await update.message.reply_text("Nothing due this week.")

    suggestion = await asyncio.to_thread(agent.get_proactive_suggestion, conn, client)
    if suggestion is not None:
        await update.message.reply_text(f"Idea: {suggestion}")


async def _handle_confirm(conn, query, commitment_id, context) -> None:
    await query.answer()
    await query.edit_message_text(
        "Confirmed.", reply_markup=_build_done_dismiss_keyboard(commitment_id)
    )


async def _handle_edit_due(conn, query, commitment_id, context) -> None:
    context.user_data["pending_edit_due"] = commitment_id
    await query.answer()
    await query.edit_message_text("What's the new due date? (YYYY-MM-DD)")


async def _handle_dismiss(conn, query, commitment_id, context) -> None:
    db.dismiss_commitment(conn, commitment_id)
    await query.answer()
    await query.edit_message_text("Dismissed.")


async def _handle_done(conn, query, commitment_id, context) -> None:
    context.user_data["pending_done"] = commitment_id
    await query.answer()
    await query.edit_message_text("How did it go? One line on her reaction.")


_BUTTON_HANDLERS = {
    "confirm": _handle_confirm,
    "edit_due": _handle_edit_due,
    "dismiss": _handle_dismiss,
    "done": _handle_done,
}


async def handle_button(update, context) -> None:
    if not _is_authorized_chat(update.effective_chat.id):
        return

    query = update.callback_query
    action, _, commitment_id_str = query.data.partition(":")
    commitment_id = int(commitment_id_str)
    conn = context.bot_data["conn"]
    await _BUTTON_HANDLERS[action](conn, query, commitment_id, context)


async def handle_error(update, context) -> None:
    if update is not None and getattr(update, "effective_chat", None) is not None:
        try:
            await update.effective_chat.send_message(
                "Something went wrong handling that. Try again?"
            )
        except Exception:
            pass


def send_reminder(reminder: dict) -> None:
    async def _send():
        bot_client = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
        await bot_client.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=reminder["text"])

    asyncio.run(_send())


def build_app():
    conn = db.connect(config.DB_PATH)
    db.init_schema(conn)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["conn"] = conn
    app.bot_data["client"] = client

    app.add_handler(CommandHandler("open", handle_open))
    app.add_handler(CommandHandler("week", handle_week))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(handle_error)

    return app


def main() -> None:
    app = build_app()
    app.run_polling()


if __name__ == "__main__":
    main()
