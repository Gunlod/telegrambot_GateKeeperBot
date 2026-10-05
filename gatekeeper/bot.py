from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from .blacklist import BlacklistStore, display_name
from .config import AppConfig
from .join_log import JoinLogEntry, JoinLogStore

LOGGER = logging.getLogger(__name__)


def configure_logging(config: AppConfig) -> None:
    log_path: Path = config.logging.file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, config.logging.level, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z"
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    for handler in (
        logging.StreamHandler(),
        RotatingFileHandler(
            log_path,
            maxBytes=config.logging.max_bytes,
            backupCount=config.logging.backup_count,
            encoding="utf-8",
        ),
    ):
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)


def _username_for_log(username: str | None) -> str | None:
    return f"@{username}" if username else None


def _quote(value: object) -> str:
    return str(value).replace('"', '\\"')


async def _is_chat_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
    except TelegramError:
        LOGGER.warning("Could not verify command sender's administrator status", exc_info=True)
        return False


async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    store: BlacklistStore = context.application.bot_data["blacklist_store"]
    join_log: JoinLogStore = context.application.bot_data["join_log_store"]
    action: str = context.application.bot_data["action"]
    joined_at = message.date
    join_log_entries: list[JoinLogEntry] = []
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            LOGGER.info("Skipping GateKeeperBot's own join event user_id=%d", member.id)
            continue

        username = _username_for_log(member.username)
        name = display_name(member.first_name, member.last_name)
        LOGGER.info(
            'JOIN user_id=%d username=%s display_name="%s"',
            member.id,
            username,
            _quote(name),
        )
        # Read this explicitly: other bot accounts are intentionally checked too.
        LOGGER.debug("JOIN ACCOUNT user_id=%d is_bot=%s", member.id, member.is_bot)
        join_log_entries.append(
            JoinLogEntry(
                username=username,
                display_name=name,
                numeric_id=member.id,
                joined_at=joined_at,
            )
        )

    # Persist the event before enforcing the blacklist. One multi-user join event
    # becomes one Sheets append request; a write failure is deliberately non-fatal.
    await join_log.append(chat.id, join_log_entries)

    for member in message.new_chat_members:
        if member.id == context.bot.id:
            continue
        username = _username_for_log(member.username)
        name = display_name(member.first_name, member.last_name)
        matched = store.match(member.username, name, member.id)
        if not matched:
            continue

        LOGGER.info(
            'BLACKLIST MATCH user_id=%d username=%s display_name="%s" matched=%s',
            member.id,
            username,
            _quote(name),
            matched,
        )
        # Telegram does not allow a bot to ban an administrator. Avoid an unnecessary API call.
        try:
            current_member = await context.bot.get_chat_member(chat.id, member.id)
            if current_member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
                LOGGER.warning(
                    "BAN SKIPPED chat_id=%d user_id=%d reason=target_is_administrator",
                    chat.id,
                    member.id,
                )
                continue
        except TelegramError:
            # The ban request is still useful if this status lookup fails.
            LOGGER.warning(
                "Could not check target administrator status chat_id=%d user_id=%d",
                chat.id,
                member.id,
                exc_info=True,
            )

        try:
            await context.bot.ban_chat_member(chat.id, member.id)
            if action == "kick":
                await context.bot.unban_chat_member(chat.id, member.id, only_if_banned=True)
            LOGGER.info("BAN SUCCESS chat_id=%d user_id=%d", chat.id, member.id)
        except TelegramError as exc:
            LOGGER.error(
                'BAN FAILED chat_id=%d user_id=%d error="%s"',
                chat.id,
                member.id,
                _quote(exc),
            )


async def blacklist_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not await _is_chat_admin(update, context):
        return
    store: BlacklistStore = context.application.bot_data["blacklist_store"]
    if await store.reload():
        await update.effective_message.reply_text(
            f"Blacklist reloaded. {store.snapshot.entry_count} entries loaded."
        )
    else:
        await update.effective_message.reply_text(
            "Failed to reload blacklist. Using previous cache."
        )


async def blacklist_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not await _is_chat_admin(update, context):
        return
    snapshot = context.application.bot_data["blacklist_store"].snapshot
    last_updated = (
        snapshot.last_updated.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        if snapshot.last_updated
        else "Never (no successful spreadsheet load)"
    )
    await update.effective_message.reply_text(
        "GateKeeperBot status\n\n"
        f"Blacklist entries: {snapshot.entry_count}\n"
        f"Username entries: {len(snapshot.usernames)}\n"
        f"Display name entries: {len(snapshot.display_names)}\n"
        f"Numeric ID entries: {len(snapshot.numeric_ids)}\n"
        f"Last updated: {last_updated}"
    )


async def refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.application.bot_data["blacklist_store"].reload()


async def post_init(application: Application) -> None:
    store: BlacklistStore = application.bot_data["blacklist_store"]
    await store.reload()
    interval: int = application.bot_data["refresh_interval"]
    if application.job_queue is None:  # guarded by the job-queue dependency extra
        raise RuntimeError("python-telegram-bot job-queue extra is required")
    application.job_queue.run_repeating(refresh_job, interval=interval, first=interval)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.error("Unhandled Telegram update error update=%r", update, exc_info=context.error)


def build_application(config: AppConfig) -> Application:
    store = BlacklistStore(config.google)
    join_log = JoinLogStore(config.google)
    application = (
        ApplicationBuilder()
        .token(config.telegram.bot_token)
        .post_init(post_init)
        .build()
    )
    application.bot_data["blacklist_store"] = store
    application.bot_data["join_log_store"] = join_log
    application.bot_data["action"] = config.telegram.action
    application.bot_data["refresh_interval"] = config.blacklist.refresh_interval
    group_filter = filters.ChatType.GROUPS
    application.add_handler(CommandHandler("blacklist_reload", blacklist_reload, filters=group_filter))
    application.add_handler(CommandHandler("blacklist_status", blacklist_status, filters=group_filter))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    application.add_error_handler(error_handler)
    return application
