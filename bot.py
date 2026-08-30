"""
Telegram-бот для spaced repetition по олимпиадной математике.

Управление — через кнопки постоянного меню внизу экрана (не нужно
руками набирать команды), либо теми же слэш-командами:

    /start   - приветствие + показывает твой Telegram user_id
    /add     - добавить карточку (формула/теорема)
    /review  - начать сессию повторения due-карточек
    /list    - список всех карточек с ID и темой (первые 50)
    /delete  - удалить конкретную карточку по ID
    /stats   - статистика (сколько карточек всего / due сегодня)
    /cancel  - отменить текущий диалог (например, добавление карточки)

Пополнение базы без ручного ввода: import_seed.py заливает готовый
набор карточек из seed_cards.json (нужен твой user_id — покажет /start).

Запуск:
    1. python -m venv venv && venv\\Scripts\\activate  (Windows)
    2. pip install -r requirements.txt
    3. Создать .env (см. .env.example) и вписать BOT_TOKEN
    4. python bot.py
"""

import asyncio
import html
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

import db
import render
import sm2

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
router = Router()


# ---------- Тексты кнопок главного меню ----------

BTN_ADD = "➕ Добавить карточку"
BTN_REVIEW = "📚 Повторить"
BTN_LIST = "📋 Список карточек"
BTN_STATS = "📊 Статистика"
BTN_HELP = "❓ Помощь"


# ---------- FSM состояния ----------

class AddCard(StatesGroup):
    waiting_front = State()
    waiting_back = State()
    waiting_topic = State()


class ReviewSession(StatesGroup):
    active = State()


# ---------- Клавиатуры ----------

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_REVIEW)],
            [KeyboardButton(text=BTN_LIST), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие или введи /add, /review...",
    )


def grade_keyboard(card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="😵 Плохо", callback_data=f"grade:again:{card_id}"),
                InlineKeyboardButton(text="🙂 Норм", callback_data=f"grade:good:{card_id}"),
                InlineKeyboardButton(text="😎 Легко", callback_data=f"grade:easy:{card_id}"),
            ],
            [InlineKeyboardButton(text="🗑 Удалить карточку", callback_data=f"del:{card_id}")],
        ]
    )


def show_answer_keyboard(card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Показать ответ", callback_data=f"show:{card_id}")]
        ]
    )


def skip_topic_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Без темы", callback_data="skip_topic")]
        ]
    )


# ---------- Вспомогательное форматирование ----------

def esc(text: str) -> str:
    """Экранирует пользовательский текст для безопасной вставки в HTML-разметку."""
    return html.escape(text)


def format_card_front(front: str, topic: str) -> str:
    text = f"📋 <b>{esc(front)}</b>"
    if topic:
        text += f"\n🏷 <i>{esc(topic)}</i>"
    return text


def format_card_full(front: str, back: str, topic: str) -> str:
    text = f"📋 <b>{esc(front)}</b>"
    if topic:
        text += f"\n🏷 <i>{esc(topic)}</i>"
    text += f"\n\n➡️ {esc(back)}"
    return text


def _card_png(
    card,
    *,
    revealed: bool,
    progress: str = "",
    footer: str = "",
) -> bytes:
    return render.render_card(
        card["front"],
        card["back"],
        card["topic"] or "",
        revealed=revealed,
        progress=progress,
        footer=footer,
    )


def _photo(png: bytes, name: str = "card.png") -> BufferedInputFile:
    return BufferedInputFile(png, filename=name)


# ---------- Базовые команды ----------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Привет!</b> Это бот для повторения формул и теорем "
        "по олимпиадной математике (spaced repetition, алгоритм SM-2).\n\n"
        "Пользуйся кнопками меню внизу экрана 👇\n\n"
        f"Твой Telegram ID: <code>{message.from_user.id}</code>\n"
        "<i>Он нужен для команды python import_seed.py &lt;id&gt;, "
        "чтобы залить стартовый набор карточек в базу.</i>",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Как пользоваться:</b>\n\n"
        f"{BTN_ADD} — добавить свою карточку (вопрос → ответ → тема)\n"
        f"{BTN_REVIEW} — начать сессию повторения due-карточек\n"
        f"{BTN_LIST} — список всех карточек с ID\n"
        f"{BTN_STATS} — сколько карточек всего и на сегодня\n\n"
        "Во время повторения можно удалить карточку кнопкой 🗑, "
        "или командой /delete &lt;id&gt; в любой момент.\n\n"
        "Формулы пиши в LaTeX между долларами, например:\n"
        "<code>$a+b \\ge 2\\sqrt{ab}$</code>"
    )


@router.message(Command("stats"))
@router.message(F.text == BTN_STATS)
async def cmd_stats(message: Message) -> None:
    user_id = message.from_user.id
    total = db.count_total(user_id)
    due = db.count_due(user_id)
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Всего карточек: <b>{total}</b>\n"
        f"На сегодня к повтору: <b>{due}</b>"
    )


@router.message(Command("list"))
@router.message(F.text == BTN_LIST)
async def cmd_list(message: Message) -> None:
    user_id = message.from_user.id
    cards = db.list_cards(user_id, limit=50)
    if not cards:
        await message.answer("Карточек пока нет — добавь через ➕ или залей seed-набор.")
        return

    lines = [
        f"<code>#{c['id']}</code> [{esc(c['topic'] or 'без темы')}] {esc(c['front'])}"
        for c in cards
    ]
    text = "📋 <b>Твои карточки:</b>\n\n" + "\n".join(lines)
    total = db.count_total(user_id)
    if total > 50:
        text += f"\n\n<i>...показаны первые 50 из {total}</i>"
    await message.answer(text)


@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Использование: /delete &lt;id&gt;\nID карточки смотри в 📋 Список")
        return

    card_id = int(args[1].strip())
    deleted = db.delete_card(card_id, message.from_user.id)
    if deleted:
        await message.answer(f"Карточка #{card_id} удалена ✅")
    else:
        await message.answer(f"Карточка #{card_id} не найдена (или не твоя).")


# ---------- Добавление карточки ----------

@router.message(Command("add"))
@router.message(F.text == BTN_ADD)
async def cmd_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddCard.waiting_front)
    await message.answer(
        "✏️ Введи <b>вопрос / название теоремы</b> (лицевая сторона карточки).\n"
        "/cancel — отменить"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_keyboard())


@router.message(AddCard.waiting_front)
async def add_front(message: Message, state: FSMContext) -> None:
    await state.update_data(front=message.text)
    await state.set_state(AddCard.waiting_back)
    await message.answer(
        "✏️ Теперь введи <b>ответ</b> (формула / формулировка).\n"
        "LaTeX: <code>$c^2 = a^2+b^2-2ab\\cos C$</code>"
    )


@router.message(AddCard.waiting_back)
async def add_back(message: Message, state: FSMContext) -> None:
    await state.update_data(back=message.text)
    await state.set_state(AddCard.waiting_topic)
    await message.answer(
        "🏷 Тема карточки (например: неравенства, теория чисел).",
        reply_markup=skip_topic_keyboard(),
    )


@router.callback_query(AddCard.waiting_topic, F.data == "skip_topic")
async def add_topic_skip_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _save_card(callback.message, state, topic="", user_id=callback.from_user.id)
    await callback.answer()


@router.message(AddCard.waiting_topic)
async def add_topic(message: Message, state: FSMContext) -> None:
    await _save_card(message, state, topic=message.text, user_id=message.from_user.id)


async def _save_card(message: Message, state: FSMContext, topic: str, user_id: int) -> None:
    data = await state.get_data()
    db.add_card(user_id=user_id, front=data["front"], back=data["back"], topic=topic)
    await state.clear()
    await message.answer("✅ Карточка сохранена!", reply_markup=main_menu_keyboard())


# ---------- Повторение ----------

@router.message(Command("review"))
@router.message(F.text == BTN_REVIEW)
async def cmd_review(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    due = db.get_due_cards(user_id)
    if not due:
        await message.answer("🎉 На сегодня карточек к повтору нет!")
        return

    await state.update_data(queue=[row["id"] for row in due], total=len(due))
    await state.set_state(ReviewSession.active)
    await _send_next_card(message, state)


async def _send_next_card(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    queue = data.get("queue", [])
    total = data.get("total", len(queue))

    if not queue:
        await state.clear()
        await message.answer("✅ Сессия повторения завершена!", reply_markup=main_menu_keyboard())
        return

    card_id = queue[0]
    card = db.get_card(card_id)
    if card is None:
        queue.pop(0)
        await state.update_data(queue=queue)
        await _send_next_card(message, state)
        return

    position = total - len(queue) + 1
    progress = f"карточка {position} из {total}"
    try:
        png = _card_png(card, revealed=False, progress=progress)
        await message.answer_photo(
            _photo(png),
            reply_markup=show_answer_keyboard(card_id),
        )
    except Exception:
        logging.exception("не удалось срендерить карточку #%s", card_id)
        text = f"<i>{esc(progress)}</i>\n\n" + format_card_front(card["front"], card["topic"])
        await message.answer(text, reply_markup=show_answer_keyboard(card_id))


@router.callback_query(F.data.startswith("show:"))
async def show_answer(callback: CallbackQuery, state: FSMContext) -> None:
    card_id = int(callback.data.split(":")[1])
    card = db.get_card(card_id)
    if card is None:
        await callback.answer("Карточка не найдена")
        return
    data = await state.get_data()
    queue = data.get("queue", [])
    total = data.get("total", 1)
    position = total - len(queue) + 1 if queue else total
    progress = f"карточка {position} из {total}"
    try:
        png = _card_png(card, revealed=True, progress=progress)
        await callback.message.edit_media(
            InputMediaPhoto(media=_photo(png, "answer.png")),
            reply_markup=grade_keyboard(card_id),
        )
    except Exception:
        logging.exception("не удалось показать ответ #%s", card_id)
        await callback.message.answer(
            format_card_full(card["front"], card["back"], card["topic"]),
            reply_markup=grade_keyboard(card_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def delete_during_review(callback: CallbackQuery, state: FSMContext) -> None:
    card_id = int(callback.data.split(":")[1])
    deleted = db.delete_card(card_id, callback.from_user.id)
    notice = "🗑 Карточка удалена." if deleted else "Карточка не найдена."
    try:
        await callback.message.edit_caption(notice)
    except Exception:
        try:
            await callback.message.edit_text(notice)
        except Exception:
            await callback.message.answer(notice)
    await callback.answer()

    data = await state.get_data()
    queue = data.get("queue", [])
    if queue and queue[0] == card_id:
        queue.pop(0)
        await state.update_data(queue=queue)
    await _send_next_card(callback.message, state)


@router.callback_query(F.data.startswith("grade:"))
async def grade_answer(callback: CallbackQuery, state: FSMContext) -> None:
    _, grade, card_id_str = callback.data.split(":")
    card_id = int(card_id_str)
    card = db.get_card(card_id)
    if card is None:
        await callback.answer("Карточка не найдена")
        return

    result = sm2.review(
        sm2.ReviewState(
            ease=card["ease"], interval=card["interval"], repetitions=card["repetitions"]
        ),
        grade,
    )
    next_date = sm2.next_review_date(result.interval)
    db.update_card_review(card_id, result.ease, result.interval, result.repetitions, next_date)

    grade_emoji = {"again": "😵", "good": "🙂", "easy": "😎"}[grade]
    footer = (
        f"{grade_emoji} следующее повторение: {next_date.strftime('%d.%m.%Y')} "
        f"(через {result.interval} дн.)"
    )
    data = await state.get_data()
    queue = data.get("queue", [])
    total = data.get("total", 1)
    position = total - len(queue) + 1 if queue else total
    try:
        png = _card_png(
            card,
            revealed=True,
            progress=f"карточка {position} из {total}",
            footer=footer,
        )
        await callback.message.edit_media(InputMediaPhoto(media=_photo(png, "graded.png")))
    except Exception:
        logging.exception("не удалось обновить карточку после оценки #%s", card_id)
        await callback.message.answer(
            format_card_full(card["front"], card["back"], card["topic"]) + f"\n\n{esc(footer)}"
        )
    await callback.answer()

    data = await state.get_data()
    queue = data.get("queue", [])
    if queue and queue[0] == card_id:
        queue.pop(0)
        await state.update_data(queue=queue)
    await _send_next_card(callback.message, state)


# ---------- Точка входа ----------

async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Создай .env на основе .env.example")

    db.init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
