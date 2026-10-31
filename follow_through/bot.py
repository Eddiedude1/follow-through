import asyncio
from datetime import datetime, timedelta, timezone

import anthropic
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from follow_through import agent, config, db


def _build_commitment_keyboard(commitment_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("Confirm", callback_data=f"confirm:{commitment_id}"),
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
    result = agent.run_agent(conn, message, client)
    await update.message.reply_text(result.final_text)


async def handle_message(update, context) -> None:
    conn = context.bot_data["conn"]

    if "pending_edit_due" in context.user_data:
        commitment_id = context.user_data.pop("pending_edit_due")
        db.update_commitment_due(conn, commitment_id, update.message.text.strip())
        await update.message.reply_text("Due date updated.")
        return

    if "pending_done" in context.user_data:
        await handle_done_reply(update, context)
        return

    client = context.bot_data["client"]
    before_ids = {c["id"] for c in db.list_open_commitments(conn)}
    result = agent.run_agent(conn, update.message.text, client)
    after = db.list_open_commitments(conn)
    new_commitments = [c for c in after if c["id"] not in before_ids]

    await update.message.reply_text(result.final_text)
    for commitment in new_commitments:
        await update.message.reply_text(
            f"{commitment['act']} — due {commitment['due']}",
            reply_markup=_build_commitment_keyboard(commitment["id"]),
        )


async def handle_open(update, context) -> None:
    conn = context.bot_data["conn"]
    commitments = db.list_open_commitments(conn)
    if not commitments:
        await update.message.reply_text("Nothing open right now.")
        return
    lines = [f"- {c['act']} (due {c['due']})" for c in commitments]
    await update.message.reply_text("Open commitments:\n" + "\n".join(lines))


async def handle_week(update, context) -> None:
    conn = context.bot_data["conn"]
    client = context.bot_data.get("client")

    cutoff = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    due_this_week = [c for c in db.list_open_commitments(conn) if c["due"] <= cutoff]

    if due_this_week:
        lines = [f"- {c['act']} (due {c['due']})" for c in due_this_week]
        await update.message.reply_text("Due this week:\n" + "\n".join(lines))
    else:
        await update.message.reply_text("Nothing due this week.")

    suggestion = agent.get_proactive_suggestion(conn, client)
    if suggestion is not None:
        await update.message.reply_text(f"Idea: {suggestion}")


async def _handle_confirm(conn, query, commitment_id, context) -> None:
    await query.answer()
    await query.edit_message_text("Confirmed.")


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
    query = update.callback_query
    action, _, commitment_id_str = query.data.partition(":")
    commitment_id = int(commitment_id_str)
    conn = context.bot_data["conn"]
    await _BUTTON_HANDLERS[action](conn, query, commitment_id, context)


def send_reminder(reminder: dict) -> None:
    async def _send():
        bot_client = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
        await bot_client.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=reminder["text"])

    asyncio.run(_send())


def build_app():
    conn = db.connect(config.DB_PATH)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["conn"] = conn
    app.bot_data["client"] = client

    app.add_handler(CommandHandler("open", handle_open))
    app.add_handler(CommandHandler("week", handle_week))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


def main() -> None:
    app = build_app()
    app.run_polling()


if __name__ == "__main__":
    main()
