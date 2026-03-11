import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, date, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials

# ======== НАСТРОЙКИ ========
BOT_TOKEN = "8638719493:AAFGAYy42JLNPwaKMAK889FGvvYXhAS1tY0"
GSHEET_ID = "17fAKPY0DqBKW5E-7uviyyF9jfPXDqIl_2SGXZmo63hY"

# Пользователь, которому шлём уведомления о новых рекламациях
NOTIFY_USER_ID = 292361413  # V_Tenyakov (Теняков Владимир)

logging.basicConfig(level=logging.INFO)

# Часовой пояс (пример: Владивосток UTC+10)
LOCAL_TZ = timezone(timedelta(hours=10))

def now_local() -> datetime:
    """Текущее время в нужном часовом поясе."""
    return datetime.now(tz=LOCAL_TZ)

# Точки
POINTS = ["Романи", "Диди", "Центр", "Меоре"]

# ======== FSM СОСТОЯНИЯ ========
class ReklamaciaForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_point = State()
    waiting_for_product_name = State()
    waiting_for_production_date = State()
    waiting_for_reason = State()

# ======== GOOGLE SHEETS КЛИЕНТ ========
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

creds = Credentials.from_service_account_file(
    "data/service_account_real.json",
    scopes=SCOPES,
)
gc = gspread.service_account(filename="data/service_account_real.json")
sh = gc.open_by_key(GSHEET_ID)
ws = sh.sheet1                    # лист с рекламациями
users_ws = sh.worksheet("users")  # лист с сотрудниками

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def get_user_full_name(user_id: int) -> str | None:
    """Вернуть Фамилию Имя по user_id из листа users, если уже зарегистрирован."""
    try:
        col_user_ids = users_ws.col_values(1)   # колонка A: user_id
        col_full_names = users_ws.col_values(3) # колонка C: full_name
    except Exception:
        return None

    uid = str(user_id)
    for i in range(1, len(col_user_ids)):  # пропускаем шапку
        if col_user_ids[i] == uid:
            if i < len(col_full_names):
                return col_full_names[i]
            return ""
    return None

def register_user(user: types.User, full_name: str):
    """Добавить пользователя в лист users."""
    users_ws.append_row(
        [
            user.id,
            user.username or "",
            full_name,
            now_local().strftime("%d.%m.%Y %H:%M"),
        ],
        value_input_option="USER_ENTERED",
    )

def save_to_google_sheet(data: dict):
    """Добавить строку в Google‑таблицу (с Фамилией и Имем сотрудника)."""
    row = [
        data.get("employee", ""),          # Фамилия Имя
        data.get("datetime", ""),
        data.get("point", ""),
        data.get("product_name", ""),
        data.get("production_date", ""),
        data.get("reason", ""),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")

async def notify_about_claim(data: dict):
    """
    Отправить уведомление о новой рекламации
    пользователю NOTIFY_USER_ID.
    """
    text = (
        "<b>Новая рекламация</b>\n\n"
        f"👩‍🍳 <bСотрудник:</b> {data.get('employee', '—')}\n"
        f"🕐 <b>Дата и время:</b> {data.get('datetime', '—')}\n"
        f"🏪 <b>Точка:</b> {data.get('point', '—')}\n"
        f"📦 <b>Название ТСП:</b> {data.get('product_name', '—')}\n"
        f"📅 <b>Дата производства ТСП:</b> {data.get('production_date', '—')}\n"
        f"❓ <b>Причина:</b> {data.get('reason', '—')}\n"
    )
    try:
        await bot.send_message(NOTIFY_USER_ID, text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление пользователю {NOTIFY_USER_ID}: {e}")

# ======== ХЭНДЛЕРЫ ========

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """
    Сразу запускаем анкету:
    либо спрашиваем ФИО, либо показываем выбор точки.
    """
    await state.clear()

    user_full_name = get_user_full_name(message.from_user.id)

    if not user_full_name:
        await message.answer(
            "👋 Давайте познакомимся.\n\n"
            "Введите, пожалуйста, вашу <b>Фамилию и Имя</b> (как в отчётах):",
            parse_mode="HTML",
        )
        await state.set_state(ReklamaciaForm.waiting_for_name)
        return

    now_str = now_local().strftime("%d.%m.%Y %H:%M")
    await state.update_data(datetime=now_str, employee=user_full_name)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=name)] for name in POINTS],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await message.answer(
        f"🕐 <b>Дата и время рекламации:</b> {now_str}\n\n"
        "🏪 Выберите <b>точку</b> из списка или введите своё название:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await state.set_state(ReklamaciaForm.waiting_for_point)

@dp.message(ReklamaciaForm.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    if len(full_name.split()) < 2:
        await message.answer("⚠️ Пожалуйста, введите Фамилию и Имя полностью.")
        return

    register_user(message.from_user, full_name)

    now_str = now_local().strftime("%d.%m.%Y %H:%M")
    await state.update_data(datetime=now_str, employee=full_name)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=name)] for name in POINTS],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await message.answer(
        f"✅ Спасибо, {full_name}.\n\n"
        f"🕐 <b>Дата и время рекламации:</b> {now_str}\n\n"
        "🏪 Теперь выберите <b>точку</b> из списка или введите своё название:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await state.set_state(ReklamaciaForm.waiting_for_point)

@dp.message(ReklamaciaForm.waiting_for_point)
async def process_point(message: types.Message, state: FSMContext):
    await state.update_data(point=message.text)
    await message.answer(
        "📦 Введите <b>название ТСП</b> (товара).\n"
        "Можете писать просто название, бот сам добавит «ТСП » в начало.",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove(),  # убрать кнопки точек
    )
    await state.set_state(ReklamaciaForm.waiting_for_product_name)

@dp.message(ReklamaciaForm.waiting_for_product_name)
async def process_product_name(message: types.Message, state: FSMContext):
    text = message.text.strip()

    # если пользователь не написал ТСП, добавляем автоматически (без учёта регистра)
    if not text.lower().startswith("тсп"):
        text = f"ТСП {text}"

    await state.update_data(product_name=text)

    await message.answer(
        "📅 Введите <b>дату производства ТСП</b>.\n"
        "Форматы: ДД.ММ.ГГГГ или ДД.ММ (год подставится текущий).\n"
        "Например: 05.03.2026 или 05.03",
        parse_mode="HTML",
    )
    await state.set_state(ReklamaciaForm.waiting_for_production_date)

@dp.message(ReklamaciaForm.waiting_for_production_date)
async def process_production_date(message: types.Message, state: FSMContext):
    text = message.text.strip()

    parsed_date = None

    # пробуем два формата: с годом и без
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%d.%m":
                dt = dt.replace(year=now_local().year)
            parsed_date = dt.date()
            break
        except ValueError:
            continue

    if not parsed_date:
        await message.reply(
            "⚠️ Не смог разобрать дату.\n"
            "Пожалуйста, введите дату в формате ДД.ММ.ГГГГ или ДД.ММ.\n"
            "Примеры: 11.03.2026 или 11.03",
        )
        return  # остаёмся в этом же состоянии, не падаем

    await state.update_data(production_date=parsed_date.strftime("%d.%m.%Y"))

    await message.answer("❓ Введите <b>причину рекламации</b>:", parse_mode="HTML")
    await state.set_state(ReklamaciaForm.waiting_for_reason)

@dp.message(ReklamaciaForm.waiting_for_reason)
async def process_reason(message: types.Message, state: FSMContext):
    await state.update_data(reason=message.text)

    data = await state.get_data()
    save_to_google_sheet(data)

    # Уведомление ответственному пользователю
    await notify_about_claim(data)

    summary = (
        "✅ <b>Рекламация зарегистрирована!</b>\n\n"
        f"👩‍🍳 <b>Сотрудник:</b> {data.get('employee', '—')}\n"
        f"🕐 <b>Дата и время:</b> {data.get('datetime', '—')}\n"
        f"🏪 <b>Точка:</b> {data.get('point', '—')}\n"
        f"📦 <b>Название ТСП:</b> {data.get('product_name', '—')}\n"
        f"📅 <b>Дата производства ТСП:</b> {data.get('production_date', '—')}\n"
        f"❓ <b>Причина:</b> {data.get('reason', '—')}\n\n"
        "Данные записаны в Google‑таблицу."
    )

    await message.answer(summary, parse_mode="HTML")
    await state.clear()

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
