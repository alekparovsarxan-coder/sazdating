import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from dotenv import load_dotenv

from db import DB, haversine
from texts import (
    APPROVED,
    ASK_AGE,
    ASK_BIO,
    ASK_CITY,
    ASK_GENDER,
    ASK_LOC,
    ASK_LOOKING,
    ASK_NAME,
    ASK_PHOTO,
    BANNED,
    LIMIT,
    MATCH,
    NOT_APPROVED,
    NO_PROFILES,
    NUDGES,
    PAY_INFO,
    PENDING,
    PREMIUM_INFO,
    REJECTED,
    SUPER_IN,
    SUPER_LIMIT,
    SUPER_NEED,
    UNBANNED,
    WELCOME,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
DB_PATH = os.getenv("DB_PATH", "sazdating.db")
FREE_LIKES = 30
PRICE_LIKES = 100
PRICE_SUPER = 25
PRICE_PREMIUM = 1000
PREMIUM_DAYS = 7

router = Router()
db = DB(DB_PATH)
CITIES = ["Bakı", "Gəncə", "Sumqayıt", "Mingəçevir", "Şəki", "Lənkəran", "Naxçıvan", "Qəbələ", "Digər"]
REASONS = ["Saxta şəkil", "18-dən aşağı", "Təhqir", "Spam", "Digər"]


class Reg(StatesGroup):
    gender = State()
    looking = State()
    name = State()
    age = State()
    city = State()
    loc = State()
    bio = State()
    photo = State()


class Edit(StatesGroup):
    value = State()


class Cast(StatesGroup):
    text = State()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def main_kb(uid: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="Lent"), KeyboardButton(text="Profilim")],
        [KeyboardButton(text="Matçlar"), KeyboardButton(text="Məni bəyənənlər")],
        [KeyboardButton(text="Superlike"), KeyboardButton(text="Ödəniş")],
        [KeyboardButton(text="Premium"), KeyboardButton(text="Konum yenilə")],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(text="Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def loc_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Konumumu göndər", request_location=True)]],
        resize_keyboard=True,
    )


def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Oğlan", callback_data="g:oglan"),
        InlineKeyboardButton(text="Qız", callback_data="g:qiz"),
    ]])


def looking_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Qız", callback_data="l:qiz"), InlineKeyboardButton(text="Oğlan", callback_data="l:oglan")],
        [InlineKeyboardButton(text="Hamı", callback_data="l:hami")],
    ])


def city_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for c in CITIES:
        row.append(InlineKeyboardButton(text=c, callback_data=f"c:{c}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Keç", callback_data=f"s:skip:{uid}"),
            InlineKeyboardButton(text="Bəyən", callback_data=f"s:like:{uid}"),
            InlineKeyboardButton(text="Superlike", callback_data=f"s:super:{uid}"),
        ],
        [
            InlineKeyboardButton(text="Şikayət", callback_data=f"rep:{uid}"),
            InlineKeyboardButton(text="Blok", callback_data=f"s:block:{uid}"),
            InlineKeyboardButton(text="Geri al", callback_data="undo"),
        ],
    ])


def pay_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+30 bəyənmə · 100 Stars", callback_data="buy:likes")],
        [InlineKeyboardButton(text="1 Superlike · 25 Stars", callback_data="buy:super")],
        [InlineKeyboardButton(text="Premium 7 gün · 1000 Stars", callback_data="buy:premium")],
    ])


def write_kb(uid: int, username: str | None) -> InlineKeyboardMarkup:
    url = f"https://t.me/{username}" if username else f"tg://user?id={uid}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Yaz", url=url)]])


def dist_text(me, other) -> str:
    if not me or not other or not me["lat"] or not other["lat"]:
        return other["city"] if other else "—"
    km = haversine(me["lat"], me["lon"], other["lat"], other["lon"])
    if km < 1:
        return f"{int(km * 1000)} m"
    return f"{km:.1f} km"


def card_text(row, me=None) -> str:
    tick = db.tick(row)
    dist = dist_text(me, row) if me else row["city"]
    return f"<b>{row['name']}</b>{tick}, {row['age']}\n{row['city']} · {dist}\n\n{row['bio'] or '—'}"


async def gate(message: Message) -> bool:
    row = await db.get(message.from_user.id)
    if not row:
        await message.answer("Əvvəl /start ilə anket yarat.")
        return False
    if row["status"] == "banned":
        await message.answer(BANNED)
        return False
    if row["status"] != "approved":
        total, _, _, _ = await db.counts()
        min_users = await db.setting("min_users", "100")
        await message.answer(NOT_APPROVED + "\n" + PENDING.format(min=min_users, total=total))
        return False
    return True


async def send_card(message: Message, row, me) -> None:
    await message.answer_photo(row["photo_id"], caption=card_text(row, me), reply_markup=card_kb(row["user_id"]))


async def show_next(message: Message, user_id: int) -> None:
    me = await db.get(user_id)
    if not me or me["status"] != "approved":
        return
    row = await db.next_profile(me)
    if not row:
        await message.answer(NO_PROFILES, reply_markup=main_kb(user_id))
        return
    await send_card(message, row, me)


async def notify_admins(bot: Bot, text: str, photo: str | None = None, kb=None) -> None:
    for aid in ADMIN_IDS:
        try:
            if photo:
                await bot.send_photo(aid, photo, caption=text, reply_markup=kb)
            else:
                await bot.send_message(aid, text, reply_markup=kb)
        except Exception:
            logging.exception("admin notify failed")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get(message.from_user.id)
    if user and user["status"] == "banned":
        await message.answer(BANNED)
        return
    if user and user["status"] == "approved" and user["photo_id"]:
        await message.answer("Yenidən xoş gəldin.", reply_markup=main_kb(message.from_user.id))
        return
    if user and user["status"] == "pending":
        total, _, _, _ = await db.counts()
        min_users = await db.setting("min_users", "100")
        await message.answer(PENDING.format(min=min_users, total=total))
        return
    ref = None
    if message.text and " " in message.text:
        arg = message.text.split(maxsplit=1)[1]
        if arg.startswith("ref") and arg[3:].isdigit():
            ref = int(arg[3:])
    await state.update_data(referrer=ref)
    await message.answer(WELCOME, reply_markup=ReplyKeyboardRemove())
    await message.answer(ASK_GENDER, reply_markup=gender_kb())
    await state.set_state(Reg.gender)


@router.callback_query(Reg.gender, F.data.startswith("g:"))
async def reg_gender(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(gender=cb.data.split(":")[1])
    await cb.message.edit_text(ASK_LOOKING, reply_markup=looking_kb())
    await state.set_state(Reg.looking)
    await cb.answer()


@router.callback_query(Reg.looking, F.data.startswith("l:"))
async def reg_looking(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(looking=cb.data.split(":")[1])
    await cb.message.edit_text(ASK_NAME)
    await state.set_state(Reg.name)
    await cb.answer()


@router.message(Reg.name)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not re.fullmatch(r"[A-Za-zƏəÖöÜüIıÇçŞşĞğ][A-Za-zƏəÖöÜüIıÇçŞşĞğ \-]{1,23}", name):
        await message.answer("Ad 2–24 hərf olsun.")
        return
    await state.update_data(name=name)
    await message.answer(ASK_AGE)
    await state.set_state(Reg.age)


@router.message(Reg.age)
async def reg_age(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit():
        await message.answer("Yalnız rəqəm.")
        return
    age = int(message.text)
    if age < 18:
        await message.answer("18-dən aşağı qəbul edilmir.")
        return
    if age > 70:
        await message.answer("18–70 arası yaz.")
        return
    await state.update_data(age=age)
    await message.answer(ASK_CITY, reply_markup=city_kb())
    await state.set_state(Reg.city)


@router.callback_query(Reg.city, F.data.startswith("c:"))
async def reg_city(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city=cb.data.split(":", 1)[1])
    await cb.message.answer(ASK_LOC, reply_markup=loc_kb())
    await state.set_state(Reg.loc)
    await cb.answer()


@router.message(Reg.loc, F.location)
async def reg_loc(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("only_loc"):
        await db.set_field(message.from_user.id, "lat", message.location.latitude)
        await db.set_field(message.from_user.id, "lon", message.location.longitude)
        await state.clear()
        await message.answer("Konum yeniləndi. Yaxın anketlər buna görə gələcək.", reply_markup=main_kb(message.from_user.id))
        return
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await message.answer(ASK_BIO, reply_markup=ReplyKeyboardRemove())
    await state.set_state(Reg.bio)


@router.message(Reg.loc)
async def reg_loc_bad(message: Message) -> None:
    await message.answer("Konum düyməsindən göndər.", reply_markup=loc_kb())


@router.message(Reg.bio)
async def reg_bio(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "/skip":
        text = ""
    if len(text) > 300:
        await message.answer("300 simvoldan qısa.")
        return
    await state.update_data(bio=text)
    await message.answer(ASK_PHOTO)
    await state.set_state(Reg.photo)


@router.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    payload = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "name": data["name"],
        "age": data["age"],
        "gender": data["gender"],
        "looking": data["looking"],
        "city": data["city"],
        "bio": data.get("bio") or "",
        "photo_id": message.photo[-1].file_id,
        "lat": data["lat"],
        "lon": data["lon"],
        "referrer": data.get("referrer"),
    }
    await db.save_profile(payload)
    if payload["referrer"]:
        ref = await db.get(payload["referrer"])
        if ref:
            await db.add_extra_likes(payload["referrer"], 5)
    await state.clear()
    total, _, _, _ = await db.counts()
    min_users = await db.setting("min_users", "100")
    await message.answer(PENDING.format(min=min_users, total=total), reply_markup=main_kb(message.from_user.id))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Təsdiqlə", callback_data=f"adm:ok:{message.from_user.id}"),
        InlineKeyboardButton(text="Rədd", callback_data=f"adm:no:{message.from_user.id}"),
    ], [
        InlineKeyboardButton(text="Ban", callback_data=f"adm:ban:{message.from_user.id}"),
    ]])
    uname = f"@{message.from_user.username}" if message.from_user.username else "username yoxdur"
    text = (
        "<b>Yeni anket</b>\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"{payload['name']}, {payload['age']} · {payload['gender']} → {payload['looking']}\n"
        f"{payload['city']} · {uname}\n"
        f"Konum: {payload['lat']:.4f}, {payload['lon']:.4f}\n\n"
        f"{payload['bio'] or '—'}\n\n"
        f"Ümumi qeydiyyat: {total}/{min_users}"
    )
    await notify_admins(bot, text, payload["photo_id"], kb)


@router.message(Reg.photo)
async def reg_photo_bad(message: Message) -> None:
    await message.answer("Şəkil göndər.")


@router.message(F.text == "Lent")
async def feed(message: Message) -> None:
    if await gate(message):
        await show_next(message, message.from_user.id)


@router.message(F.text == "Profilim")
async def my_profile(message: Message) -> None:
    row = await db.get(message.from_user.id)
    if not row or not row["photo_id"]:
        await message.answer("Anket yoxdur. /start")
        return
    left = await db.likes_left(row)
    left_s = "limitsiz" if left is None else str(left)
    prem = "Premium 🟡" if db.is_premium(row) else row["status"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Bio", callback_data="e:bio"), InlineKeyboardButton(text="Şəkil", callback_data="e:photo")],
        [InlineKeyboardButton(text="Gizlət/göstər", callback_data="e:hide")],
        [InlineKeyboardButton(text="Dəvət linki", callback_data="e:ref")],
    ])
    await message.answer_photo(
        row["photo_id"],
        caption=card_text(row, row) + f"\n\nStatus: {prem}\nBəyənmə qalığı: {left_s}\nSuper kredit: {row['super_credits']}\nBaxış: {row['views']}",
        reply_markup=kb,
    )


@router.callback_query(F.data == "e:ref")
async def ref_link(cb: CallbackQuery, bot: Bot) -> None:
    me = await bot.get_me()
    await cb.message.answer(f"Dəvət linkin: https://t.me/{me.username}?start=ref{cb.from_user.id}\nHər dəvət +5 bəyənmə.")
    await cb.answer()


@router.callback_query(F.data == "e:hide")
async def hide(cb: CallbackQuery) -> None:
    row = await db.get(cb.from_user.id)
    await db.set_field(cb.from_user.id, "hidden", 0 if row["hidden"] else 1)
    await cb.answer("Profil görünürlüğü dəyişdi.", show_alert=True)


@router.callback_query(F.data.startswith("e:"))
async def edit_start(cb: CallbackQuery, state: FSMContext) -> None:
    field = cb.data.split(":")[1]
    if field in ("hide", "ref"):
        return
    await state.set_state(Edit.value)
    await state.update_data(field=field)
    await cb.message.answer("Yeni bio yaz." if field == "bio" else "Yeni şəkil göndər.")
    await cb.answer()


@router.message(Edit.value, F.photo)
async def edit_photo(message: Message, state: FSMContext) -> None:
    if (await state.get_data()).get("field") != "photo":
        return
    await db.set_field(message.from_user.id, "photo_id", message.photo[-1].file_id)
    await db.set_status(message.from_user.id, "pending")
    await state.clear()
    await message.answer("Şəkil yeniləndi və yenidən yoxlamaya düşdü.", reply_markup=main_kb(message.from_user.id))


@router.message(Edit.value, F.text)
async def edit_bio(message: Message, state: FSMContext) -> None:
    if (await state.get_data()).get("field") != "bio":
        return
    text = (message.text or "").strip()
    if len(text) > 300:
        await message.answer("300 simvoldan qısa.")
        return
    await db.set_field(message.from_user.id, "bio", text)
    await state.clear()
    await message.answer("Bio yeniləndi.", reply_markup=main_kb(message.from_user.id))


@router.message(F.text == "Konum yenilə")
async def ask_loc(message: Message, state: FSMContext) -> None:
    await state.set_state(Reg.loc)
    await state.update_data(only_loc=True)
    await message.answer(ASK_LOC, reply_markup=loc_kb())


@router.callback_query(F.data.startswith("s:"))
async def swipe(cb: CallbackQuery, bot: Bot) -> None:
    _, action, raw = cb.data.split(":")
    to_id = int(raw)
    me = await db.get(cb.from_user.id)
    if not me or me["status"] != "approved":
        await cb.answer(NOT_APPROVED, show_alert=True)
        return
    if action == "block":
        await db.block(cb.from_user.id, to_id)
        await db.swipe(cb.from_user.id, to_id, "skip")
        await cb.answer("Bloklandı.")
        await show_next(cb.message, cb.from_user.id)
        return
    if action == "like":
        if not await db.consume_like(cb.from_user.id):
            await cb.answer(LIMIT, show_alert=True)
            return
        left = await db.likes_left(await db.get(cb.from_user.id))
        if left in (5, 3, 1):
            await cb.message.answer(f"Pulsuz/əlavə bəyənmədən {left} qalıb. Ödənişdən artır.")
    if action == "super":
        result = await db.consume_super(cb.from_user.id)
        if result == "need_credit":
            await cb.answer(SUPER_NEED, show_alert=True)
            return
        if result == "premium_limit":
            await cb.answer(SUPER_LIMIT, show_alert=True)
            return
    matched = await db.swipe(cb.from_user.id, to_id, action)
    await cb.answer("Superlike getdi." if action == "super" else "Oldu.")
    other = await db.get(to_id)
    if action == "super" and other:
        try:
            await bot.send_photo(
                to_id,
                me["photo_id"],
                caption=SUPER_IN.format(
                    name=me["name"], tick=db.tick(me), age=me["age"],
                    city=me["city"], dist=dist_text(other, me), bio=me["bio"] or "—",
                ),
                reply_markup=card_kb(me["user_id"]),
            )
        except Exception:
            logging.exception("super notify")
    if matched and other:
        body = MATCH.format(
            name=other["name"], tick=db.tick(other), age=other["age"],
            city=other["city"], dist=dist_text(me, other), bio=other["bio"] or "—",
        )
        await cb.message.answer(body + "\n\nBuzqıran: Salam, anketin maraqlı gəldi.", reply_markup=write_kb(to_id, other["username"]))
        try:
            await bot.send_message(
                to_id,
                MATCH.format(
                    name=me["name"], tick=db.tick(me), age=me["age"],
                    city=me["city"], dist=dist_text(other, me), bio=me["bio"] or "—",
                ),
                reply_markup=write_kb(cb.from_user.id, cb.from_user.username),
            )
        except Exception:
            logging.exception("match notify")
    await show_next(cb.message, cb.from_user.id)


@router.callback_query(F.data == "undo")
async def undo(cb: CallbackQuery) -> None:
    row = await db.last_skip(cb.from_user.id)
    if not row:
        await cb.answer("Geri alınacaq keçid yoxdur.", show_alert=True)
        return
    await db.undo_skip(cb.from_user.id, row["to_id"])
    me = await db.get(cb.from_user.id)
    await cb.answer("Son keçid geri alındı.")
    await send_card(cb.message, row, me)


@router.callback_query(F.data.startswith("rep:"))
async def report_menu(cb: CallbackQuery) -> None:
    uid = cb.data.split(":")[1]
    rows = [[InlineKeyboardButton(text=r, callback_data=f"rr:{uid}:{i}")] for i, r in enumerate(REASONS)]
    await cb.message.answer("Şikayət səbəbi:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("rr:"))
async def report_do(cb: CallbackQuery, bot: Bot) -> None:
    _, uid, idx = cb.data.split(":")
    reason = REASONS[int(idx)]
    n = await db.report(cb.from_user.id, int(uid), reason)
    await db.block(cb.from_user.id, int(uid))
    await cb.answer("Şikayət düşdü.", show_alert=True)
    await notify_admins(
        bot,
        f"Şikayət\nHədəf: <code>{uid}</code>\nSəbəb: {reason}\nÜmumi şikayət: {n}\nGöndərən: <code>{cb.from_user.id}</code>",
        kb=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Ban", callback_data=f"adm:ban:{uid}"),
            InlineKeyboardButton(text="Aç", callback_data=f"adm:open:{uid}"),
        ]]),
    )
    await show_next(cb.message, cb.from_user.id)


@router.message(F.text == "Matçlar")
async def matches(message: Message) -> None:
    if not await gate(message):
        return
    me = await db.get(message.from_user.id)
    rows = await db.my_matches(message.from_user.id)
    if not rows:
        await message.answer("Hələ matç yoxdur.")
        return
    for row in rows[:10]:
        await message.answer_photo(row["photo_id"], caption=card_text(row, me), reply_markup=write_kb(row["user_id"], row["username"]))


@router.message(F.text == "Məni bəyənənlər")
async def who_liked(message: Message) -> None:
    if not await gate(message):
        return
    me = await db.get(message.from_user.id)
    if not db.is_premium(me):
        await message.answer("Səni bəyənənlər Premium üçündür.", reply_markup=pay_kb())
        return
    rows = await db.likes_received(message.from_user.id)
    if not rows:
        await message.answer("Hələ bəyənmə yoxdur.")
        return
    for row in rows[:10]:
        cap = card_text(row, me)
        if row["action"] == "super":
            cap = "<b>SUPERLIKE</b>\n" + cap
        await message.answer_photo(row["photo_id"], caption=cap, reply_markup=card_kb(row["user_id"]))


@router.message(F.text.in_({"Ödəniş", "Premium", "Superlike"}))
async def pay_menu(message: Message) -> None:
    row = await db.get(message.from_user.id)
    if not row:
        await message.answer("Əvvəl /start.")
        return
    left = await db.likes_left(row)
    await message.answer(
        PAY_INFO.format(left="limitsiz" if left is None else left, super=row["super_credits"]) + "\n\n" + PREMIUM_INFO,
        reply_markup=pay_kb(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery, bot: Bot) -> None:
    kind = cb.data.split(":")[1]
    catalog = {
        "likes": ("+30 bəyənmə", "Əlavə 30 bəyənmə", PRICE_LIKES, f"likes:{cb.from_user.id}"),
        "super": ("1 Superlike", "Bir superlike krediti", PRICE_SUPER, f"super:{cb.from_user.id}"),
        "premium": ("Premium 7 gün", "Limitsiz bəyənmə və sarı tik", PRICE_PREMIUM, f"premium:{cb.from_user.id}"),
    }
    title, desc, amount, payload = catalog[kind]
    await bot.send_invoice(
        cb.from_user.id, title, desc, payload, "XTR",
        [LabeledPrice(label=title, amount=amount)], provider_token="",
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def paid(message: Message) -> None:
    payload = message.successful_payment.invoice_payload
    kind, uid = payload.split(":")
    uid = int(uid)
    stars = message.successful_payment.total_amount
    await db.log_payment(uid, kind, stars)
    if kind == "likes":
        await db.add_extra_likes(uid, 30)
        await message.answer("+30 bəyənmə əlavə olundu.")
    elif kind == "super":
        await db.add_super(uid, 1)
        await message.answer("1 superlike kreditin var. Kartdakı Superlike düyməsi onu xərcləyir.")
    elif kind == "premium":
        until = await db.grant_premium(uid, PREMIUM_DAYS)
        await message.answer(f"Premium aktivdir, {until}-dək. Adında sarı tik görünəcək.")


@router.message(F.text == "Admin")
@router.message(Command("admin"))
async def admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    total, pending, approved, banned = await db.counts()
    wait = await db.setting("wait_mode", "1")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Gözləyənlər", callback_data="adm:list")],
        [InlineKeyboardButton(text="Şikayətlər", callback_data="adm:reps")],
        [InlineKeyboardButton(text="Hamıya mesaj", callback_data="adm:cast")],
        [InlineKeyboardButton(text="100-ü təsdiqlə", callback_data="adm:bulk")],
        [InlineKeyboardButton(text=f"Gözləmə rejimi: {wait}", callback_data="adm:wait")],
    ])
    await message.answer(
        f"İstifadəçi: {total}\nGözləyən: {pending}\nTəsdiqli: {approved}\nBan: {banned}\n\n"
        "Axtarış: /user 123456\nBan: /ban 123\nAç: /unban 123\nPremium: /grant 123",
        reply_markup=kb,
    )


@router.callback_query(F.data == "adm:list")
async def adm_list(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        return
    rows = await db.pending()
    if not rows:
        await cb.answer("Gözləyən yoxdur.", show_alert=True)
        return
    for row in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Təsdiqlə", callback_data=f"adm:ok:{row['user_id']}"),
            InlineKeyboardButton(text="Rədd", callback_data=f"adm:no:{row['user_id']}"),
        ]])
        await cb.message.answer_photo(row["photo_id"], caption=f"{row['name']}, {row['age']} · {row['city']}\nID {row['user_id']}", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:reps")
async def adm_reps(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        return
    rows = await db.open_reports()
    if not rows:
        await cb.answer("Açıq şikayət yoxdur.", show_alert=True)
        return
    for r in rows:
        await cb.message.answer(
            f"#{r['id']} hədəf {r['to_id']} ({r['name']})\nSəbəb: {r['reason']}\nÜmumi: {r['complaints']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Ban", callback_data=f"adm:ban:{r['to_id']}"),
                InlineKeyboardButton(text="Bağla", callback_data=f"adm:close:{r['id']}"),
            ]]),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:"))
async def adm_act(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    action = parts[1]
    if action == "cast":
        await state.set_state(Cast.text)
        await cb.message.answer("Hamıya gedəcək mesajı yaz. Ləğv: /cancel")
        await cb.answer()
        return
    if action == "wait":
        cur = await db.setting("wait_mode", "1")
        await db.set_setting("wait_mode", "0" if cur == "1" else "1")
        await cb.answer("Gözləmə rejimi dəyişdi.", show_alert=True)
        return
    if action == "bulk":
        total, _, _, _ = await db.counts()
        min_users = int(await db.setting("min_users", "100"))
        if total < min_users:
            await cb.answer(f"Hələ {total}/{min_users}.", show_alert=True)
            return
        rows = await db.pending(500)
        for row in rows:
            await db.set_status(row["user_id"], "approved")
            try:
                await bot.send_message(row["user_id"], APPROVED, reply_markup=main_kb(row["user_id"]))
            except Exception:
                pass
        await cb.answer(f"{len(rows)} nəfər təsdiqləndi.", show_alert=True)
        return
    if action == "close":
        await db.close_report(int(parts[2]))
        await cb.answer("Şikayət bağlandı.")
        return
    uid = int(parts[2])
    if action == "ok":
        wait = await db.setting("wait_mode", "1")
        total, _, _, _ = await db.counts()
        min_users = int(await db.setting("min_users", "100"))
        if wait == "1" and total < min_users:
            await cb.answer(f"Gözləmə rejimi açıqdır: {total}/{min_users}. Əvvəl Admin-dən söndür.", show_alert=True)
            return
        await db.set_status(uid, "approved")
        try:
            await bot.send_message(uid, APPROVED, reply_markup=main_kb(uid))
        except Exception:
            pass
        await cb.answer("Təsdiqləndi.")
        return
    if action == "no":
        await db.set_status(uid, "rejected")
        try:
            await bot.send_message(uid, REJECTED)
        except Exception:
            pass
        await cb.answer("Rədd edildi.")
        return
    if action == "ban":
        await db.set_status(uid, "banned")
        try:
            await bot.send_message(uid, BANNED)
        except Exception:
            pass
        await cb.answer("Ban.")
        return
    if action == "open":
        await db.set_status(uid, "approved")
        try:
            await bot.send_message(uid, UNBANNED, reply_markup=main_kb(uid))
        except Exception:
            pass
        await cb.answer("Açıldı.")


@router.callback_query(F.data == "adm:cast")
async def cast_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(Cast.text)
    await cb.message.answer("Hamıya gedəcək mesajı yaz. Ləğv: /cancel")
    await cb.answer()


@router.message(Cast.text, F.text)
async def cast_send(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Ləğv.")
        return
    ids = await db.approved_ids()
    ok = 0
    for uid in ids:
        try:
            await bot.send_message(uid, message.text)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await state.clear()
    await message.answer(f"Göndərildi: {ok}/{len(ids)}")


@router.message(Command("user"))
async def user_info(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("/user 123456")
        return
    row = await db.get(int(parts[1]))
    if not row:
        await message.answer("Tapılmadı.")
        return
    pays = await db.payments_of(row["user_id"])
    pay_s = ", ".join(f"{p['kind']}:{p['stars']}" for p in pays) or "—"
    text = (
        f"ID {row['user_id']} @{row['username']}\n"
        f"{row['name']}, {row['age']} · {row['gender']} → {row['looking']}\n"
        f"{row['city']} · {row['status']}\n"
        f"Şikayət {row['complaints']} · like {row['likes_sent']}/{row['likes_recv']} · super {row['super_sent']}/{row['super_recv']}\n"
        f"Baxış {row['views']} · premium {row['premium_until']}\n"
        f"Ödəniş: {pay_s}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Ban", callback_data=f"adm:ban:{row['user_id']}"),
        InlineKeyboardButton(text="Aç", callback_data=f"adm:open:{row['user_id']}"),
    ]])
    if row["photo_id"]:
        await message.answer_photo(row["photo_id"], caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.message(Command("ban"))
async def ban_cmd(message: Message, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return
    uid = int(parts[1])
    await db.set_status(uid, "banned")
    try:
        await bot.send_message(uid, BANNED)
    except Exception:
        pass
    await message.answer("Ban olundu.")


@router.message(Command("unban"))
async def unban_cmd(message: Message, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return
    uid = int(parts[1])
    await db.set_status(uid, "approved")
    try:
        await bot.send_message(uid, UNBANNED)
    except Exception:
        pass
    await message.answer("Açıldı.")


@router.message(Command("grant"))
async def grant_cmd(message: Message, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return
    until = await db.grant_premium(int(parts[1]), 7)
    try:
        await bot.send_message(int(parts[1]), f"Admin premium verdi, {until}-dək.")
    except Exception:
        pass
    await message.answer(until)


async def jobs(bot: Bot) -> None:
    while True:
        try:
            hour = datetime.now(timezone.utc).hour
            if hour == 14:  # 18:00 Bakı
                for row in await db.nudge_candidates():
                    text = NUDGES[row["user_id"] % len(NUDGES)]
                    try:
                        await bot.send_message(row["user_id"], text, reply_markup=main_kb(row["user_id"]))
                    except Exception:
                        pass
                    await db.mark_nudge(row["user_id"])
                    await asyncio.sleep(0.05)
            for row in await db.expiring_premium():
                left = datetime.fromisoformat(row["premium_until"]) - datetime.now(timezone.utc)
                hours = int(left.total_seconds() // 3600)
                if 1 <= hours <= 5 and row["prem_warn"] != str(hours):
                    try:
                        await bot.send_message(
                            row["user_id"],
                            f"Premium bitməsinə {hours} saat qalıb.",
                            reply_markup=pay_kb(),
                        )
                    except Exception:
                        pass
                    await db.set_field(row["user_id"], "prem_warn", str(hours))
        except Exception:
            logging.exception("jobs")
        await asyncio.sleep(600)


async def main() -> None:
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise SystemExit("BOT_TOKEN yoxdur.")
    logging.basicConfig(level=logging.INFO)
    await db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(jobs(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
