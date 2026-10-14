import asyncio
import logging
import re
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# НАСТРОЙКИ
BOT_TOKEN = "8950610248:AAEw9fk53RW1eIXso1qDwHLwBZ67U9Hld14"
ADMIN_IDS = {8345646899}
DB_PATH = "bot.db"

router = Router()


# БАЗА ДАННЫХ
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                link TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)


def list_channels():
    with db() as c:
        return c.execute(
            "SELECT * FROM channels ORDER BY title"
        ).fetchall()


def add_channel(chat_id, title, link):
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO channels VALUES (?, ?, ?)",
            (chat_id, title, link)
        )


def remove_channel(chat_id):
    with db() as c:
        c.execute(
            "DELETE FROM channels WHERE chat_id = ?",
            (chat_id,)
        )


def get_setting(key, default=""):
    with db() as c:
        row = c.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?)",
            (key, value)
        )


def save_user(user_id):
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO users VALUES (?)",
            (user_id,)
        )


def users_count():
    with db() as c:
        return c.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]


# ПРОВЕРКА ПОДПИСКИ
async def get_unsubscribed(bot, user_id):
    missing = []

    for ch in list_channels():
        try:
            member = await bot.get_chat_member(
                ch["chat_id"], user_id
            )

            subscribed = (
                member.status in (
                    "member", "administrator", "creator"
                )
                or (
                    member.status == "restricted"
                    and getattr(member, "is_member", False)
                )
            )

            if not subscribed:
                missing.append(ch)

        except Exception:
            logging.exception(
                "Ошибка проверки канала %s",
                ch["chat_id"]
            )
            missing.append(ch)

    return missing


def subscribe_keyboard(channels):
    kb = InlineKeyboardBuilder()

    for ch in channels:
        kb.button(
            text=f"📢 {ch['title']}",
            url=ch["link"]
        )

    kb.button(
        text="✅ Проверить подписку",
        callback_data="check_sub"
    )
    kb.adjust(1)

    return kb.as_markup()


async def send_access(target):
    text = get_setting(
        "success_text",
        "🎉 Спасибо за подписку! Доступ открыт."
    )
    link = get_setting("target_link")
    kb = None

    if link:
        builder = InlineKeyboardBuilder()
        builder.button(
            text="🚀 Перейти",
            url=link
        )
        kb = builder.as_markup()

    await target.answer(text, reply_markup=kb)


# ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    save_user(message.from_user.id)

    channels = list_channels()

    if not channels:
        await send_access(message)
        return

    missing = await get_unsubscribed(
        bot, message.from_user.id
    )

    if not missing:
        await send_access(message)
        return

    await message.answer(
        "👋 Чтобы продолжить, подпишитесь на каналы "
        "ниже и нажмите «Проверить подписку».",
        reply_markup=subscribe_keyboard(channels)
    )


@router.callback_query(F.data == "check_sub")
async def cb_check(call: CallbackQuery, bot: Bot):
    missing = await get_unsubscribed(
        bot, call.from_user.id
    )

    if missing:
        names = ", ".join(
            ch["title"] for ch in missing
        )
        await call.answer(
            f"Вы ещё не подписаны: {names}",
            show_alert=True
        )
        return

    await call.answer("Подписка подтверждена ✅")

    await call.message.delete()
    await call.message.answer(
        get_setting(
            "success_text",
            "🎉 Спасибо за подписку! Доступ открыт."
        ),
        reply_markup=(
            InlineKeyboardBuilder().button(
                text="🚀 Перейти",
                url=get_setting("target_link")
            ).as_markup()
            if get_setting("target_link")
            else None
        )
    )


# АДМИН-ПАНЕЛЬ
class AdminStates(StatesGroup):
    add_channel = State()
    set_link = State()
    set_text = State()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def admin_menu():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="➕ Добавить канал",
        callback_data="adm:add"
    )
    kb.button(
        text="🗑 Удалить канал",
        callback_data="adm:del"
    )
    kb.button(
        text="📋 Список каналов",
        callback_data="adm:list"
    )
    kb.button(
        text="🔗 Ссылка после подписки",
        callback_data="adm:link"
    )
    kb.button(
        text="✏️ Текст после подписки",
        callback_data="adm:text"
    )
    kb.button(
        text="📊 Статистика",
        callback_data="adm:stats"
    )

    kb.adjust(2, 1, 2, 1)
    return kb.as_markup()


def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅️ В меню",
        callback_data="adm:menu"
    )
    return kb.as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer(
        "⚙️ Админ-панель",
        reply_markup=admin_menu()
    )


@router.callback_query(F.data.startswith("adm:"))
async def admin_callbacks(
    call: CallbackQuery,
    state: FSMContext
):
    if not is_admin(call.from_user.id):
        await call.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    action = call.data.split(":", 1)[1]

    if action == "menu":
        await state.clear()
        await call.message.edit_text(
            "⚙️ Админ-панель",
            reply_markup=admin_menu()
        )

    elif action == "add":
        await state.set_state(
            AdminStates.add_channel
        )
        await call.message.edit_text(
            "Отправьте @username канала, ссылку "
            "t.me/... или ID (-100...), либо "
            "перешлите сообщение из канала.\n\n"
            "⚠️ Бот должен быть администратором канала.",
            reply_markup=back_kb()
        )

    elif action == "list":
        channels = list_channels()

        text = "\n".join(
            f"• {ch['title']} — {ch['link']}"
            for ch in channels
        ) or "Каналов пока нет."

        await call.message.edit_text(
            f"📋 Каналы:\n\n{text}",
            reply_markup=back_kb(),
            disable_web_page_preview=True
        )

    elif action == "del":
        channels = list_channels()

        if not channels:
            await call.message.edit_text(
                "Каналов пока нет.",
                reply_markup=back_kb()
            )
        else:
            kb = InlineKeyboardBuilder()

            for ch in channels:
                kb.button(
                    text=f"❌ {ch['title']}",
                    callback_data=f"rm:{ch['chat_id']}"
                )

            kb.button(
                text="⬅️ В меню",
                callback_data="adm:menu"
            )
            kb.adjust(1)

            await call.message.edit_text(
                "Выберите канал для удаления:",
                reply_markup=kb.as_markup()
            )

    elif action == "link":
        await state.set_state(
            AdminStates.set_link
        )

        current = (
            get_setting("target_link") or "не задана"
        )

        await call.message.edit_text(
            f"Текущая ссылка: {current}\n\n"
            "Отправьте новую ссылку "
            "(или «-», чтобы убрать).",
            reply_markup=back_kb(),
            disable_web_page_preview=True
        )

    elif action == "text":
        await state.set_state(
            AdminStates.set_text
        )
        await call.message.edit_text(
            "Отправьте новый текст, который "
            "увидит пользователь после подписки.",
            reply_markup=back_kb()
        )

    elif action == "stats":
        await call.message.edit_text(
            f"📊 Пользователей: {users_count()}\n"
            f"📢 Каналов: {len(list_channels())}",
            reply_markup=back_kb()
        )

    await call.answer()


@router.callback_query(F.data.startswith("rm:"))
async def admin_remove(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    chat_id = int(call.data.split(":", 1)[1])
    remove_channel(chat_id)

    await call.answer("Канал удалён")
    await call.message.edit_text(
        "✅ Канал удалён.",
        reply_markup=admin_menu()
    )


@router.message(AdminStates.add_channel)
async def admin_add_channel(
    message: Message,
    bot: Bot,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    ref = None

    origin = getattr(
        message, "forward_origin", None
    )

    if (
        origin is not None
        and getattr(origin, "chat", None) is not None
    ):
        ref = origin.chat.id

    elif message.text:
        text = message.text.strip()

        match = re.search(
            r"(?:t\.me/|@)([A-Za-z0-9_]{4,})$",
            text
        )

        if re.fullmatch(r"-?\d+", text):
            ref = int(text)
        elif match:
            ref = "@" + match.group(1)

    if ref is None:
        await message.answer(
            "Не понял. Отправьте @username, ссылку, "
            "ID или пересланное сообщение."
        )
        return

    try:
        chat = await bot.get_chat(ref)

        me = await bot.get_chat_member(
            chat.id, bot.id
        )

        if me.status not in (
            "administrator", "creator"
        ):
            await message.answer(
                "⚠️ Сначала сделайте бота "
                "администратором этого канала."
            )
            return

        if chat.username:
            link = f"https://t.me/{chat.username}"
        else:
            link = (
                await bot.create_chat_invite_link(
                    chat.id
                )
            ).invite_link

    except Exception as error:
        await message.answer(
            f"❌ Ошибка: {error}\n"
            "Проверьте, что бот добавлен в канал "
            "как администратор."
        )
        return

    add_channel(
        chat.id,
        chat.title or str(chat.id),
        link
    )

    await state.clear()
    await message.answer(
        f"✅ Канал «{chat.title}» добавлен.",
        reply_markup=admin_menu()
    )


@router.message(AdminStates.set_link)
async def admin_set_link(
    message: Message,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    value = (message.text or "").strip()

    set_setting(
        "target_link",
        "" if value == "-" else value
    )

    await state.clear()
    await message.answer(
        "✅ Ссылка сохранена.",
        reply_markup=admin_menu()
    )


@router.message(AdminStates.set_text)
async def admin_set_text(
    message: Message,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    set_setting(
        "success_text",
        message.text or ""
    )

    await state.clear()
    await message.answer(
        "✅ Текст сохранён.",
        reply_markup=admin_menu()
    )


# ЗАПУСК БОТА
async def main():
    if (
        not BOT_TOKEN
        or BOT_TOKEN == "ВСТАВЬ_СЮДА_НОВЫЙ_ТОКЕН"
    ):
        raise SystemExit(
            "Вставьте действующий токен бота в BOT_TOKEN"
        )

    logging.basicConfig(
        level=logging.INFO
    )

    init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(
        storage=MemoryStorage()
    )

    dp.include_router(router)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())