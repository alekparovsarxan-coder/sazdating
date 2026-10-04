import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

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

from db import DB, haversine, today
from i18n import t
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
OWNER_ID = 8753136288
ADMIN_IDS = {OWNER_ID}
extra = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
ADMIN_IDS |= extra
DB_PATH = os.getenv("DB_PATH", "sazdating.db")
FREE_LIKES = 30
PRICE_LIKES = 100
PRICE_SUPER = 25
PRICE_PREMIUM = 1000
PREMIUM_DAYS = 7

router = Router()
db = DB(DB_PATH)
MENU_FEED = {"🔥 Lent", "Lent", "🔥 Лента", "🔥 Feed"}
MENU_PROFILE = {"💛 Profilim", "Profilim", "💛 Профиль", "💛 Profile"}
MENU_MATCH = {"💬 Matçlar", "Matçlar", "💬 Мэтчи", "💬 Matches"}
MENU_LIKES = {"👀 Məni bəyənənlər", "Məni bəyənənlər", "👀 Bəyənmələr", "👀 Лайки", "👀 Likes"}
MENU_PAY = {"💎 Ödəniş", "Ödəniş", "👑 Premium", "Premium", "⭐ Superlike", "Superlike", "💎 Оплата", "👑 Премиум", "⭐ Суперлайк", "💎 Pay", "👑 Premium", "⭐ Superlike"}
MENU_LOC = {"📍 Konum yenilə", "Konum yenilə", "📍 Konum", "📍 Гео", "📍 Location"}
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
        [KeyboardButton(text="🔥 Lent"), KeyboardButton(text="💛 Profilim")],
        [KeyboardButton(text="💬 Matçlar"), KeyboardButton(text="👀 Məni bəyənənlər")],
        [KeyboardButton(text="⭐ Superlike"), KeyboardButton(text="💎 Ödəniş")],
        [KeyboardButton(text="👑 Premium"), KeyboardButton(text="📍 Konum yenilə")],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(text="🛠 Admin panel")])
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


async def vibe(message: Message, key: str) -> None:
    file_id = await db.setting(f"sticker:{key}", "")
    if not file_id:
        file_id = await db.setting("sticker:hi", "")
    if not file_id:
        return
    try:
        await message.answer_sticker(file_id)
    except Exception:
        logging.exception("sticker failed")


def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Azərbaycan", callback_data="lang:az"),
        InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="English", callback_data="lang:en"),
    ]])


def gender_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "boy"), callback_data="g:oglan"),
        InlineKeyboardButton(text=t(lang, "girl"), callback_data="g:qiz"),
    ]])


def looking_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "girl"), callback_data="l:qiz"),
            InlineKeyboardButton(text=t(lang, "boy"), callback_data="l:oglan"),
        ],
        [InlineKeyboardButton(text=t(lang, "all"), callback_data="l:hami")],
    ])


def loc_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "loc_btn"), request_location=True)]],
        resize_keyboard=True,
    )


def main_kb(uid: int, lang: str = "az") -> ReplyKeyboardMarkup:
    labels = t(lang, "menu")
    rows = [
        [KeyboardButton(text=labels[0]), KeyboardButton(text=labels[1])],
        [KeyboardButton(text=labels[2]), KeyboardButton(text=labels[3])],
        [KeyboardButton(text=labels[4]), KeyboardButton(text=labels[5])],
        [KeyboardButton(text=labels[6]), KeyboardButton(text=labels[7])],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(text="🛠 Admin panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if await db.is_blacklisted(message.from_user.id):
        await message.answer("Bu hesab qara siyahıdadır. Yenidən qeydiyyat bağlıdır.")
        return
    arg = ""
    if message.text and " " in message.text:
        arg = message.text.split(maxsplit=1)[1]
    if arg == "yenile":
        user = None
    if user and user["photo_id"] and user["status"] != "rejected" and arg != "yenile":
        lang = user["lang"] or "az"
        await vibe(message, "hi")
        status = {"approved": t(lang, "st_ok"), "pending": t(lang, "st_wait"), "banned": t(lang, "st_ban")}.get(user["status"], t(lang, "st_ok"))
        await message.answer(t(lang, "back").format(name=user["name"], status=status), reply_markup=main_kb(message.from_user.id, lang))
        return
    ref = int(arg[3:]) if arg.startswith("ref") and arg[3:].isdigit() else None
    await state.update_data(referrer=ref)
    await message.answer(t("az", "pick") + "\n\n" + t("ru", "pick") + "\n\n" + t("en", "pick"), reply_markup=lang_kb())
    await state.set_state(Reg.gender)


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(cb: CallbackQuery, state: FSMContext) -> None:
    lang = cb.data.split(":")[1]
    await state.update_data(lang=lang)
    await state.set_state(Reg.gender)
    await cb.message.answer(t(lang, "welcome"))
    await cb.message.answer(t(lang, "gender"), reply_markup=gender_kb(lang))
    await cb.answer()


@router.callback_query(Reg.gender, F.data.startswith("g:"))
async def reg_gender(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or "az"
    await state.update_data(gender=cb.data.split(":")[1])
    await cb.message.edit_text(t(lang, "looking"), reply_markup=looking_kb(lang))
    await state.set_state(Reg.looking)
    await cb.answer()


@router.callback_query(Reg.looking, F.data.startswith("l:"))
async def reg_looking(cb: CallbackQuery, state: FSMContext) -> None:
    lang = (await state.get_data()).get("lang") or "az"
    await state.update_data(looking=cb.data.split(":")[1])
    await cb.message.edit_text(t(lang, "name"))
    await state.set_state(Reg.name)
    await cb.answer()


@router.message(Reg.name)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not re.fullmatch(r"[A-Za-zƏəÖöÜüIıÇçŞşĞğА-Яа-яЁё][A-Za-zƏəÖöÜüIıÇçŞşĞğА-Яа-яЁё \-]{1,23}", name):
        await message.answer("Ad 2–24 hərf olsun. / Имя 2–24 буквы. / Name: 2–24 letters.")
        return
    lang = (await state.get_data()).get("lang") or "az"
    await state.update_data(name=name)
    await message.answer(t(lang, "age"))
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
    lang = (await state.get_data()).get("lang") or "az"
    await message.answer(t(lang, "city"), reply_markup=city_kb())
    await state.set_state(Reg.city)


@router.callback_query(Reg.city, F.data.startswith("c:"))
async def reg_city(cb: CallbackQuery, state: FSMContext) -> None:
    lang = (await state.get_data()).get("lang") or "az"
    await state.update_data(city=cb.data.split(":", 1)[1])
    await cb.message.answer(t(lang, "loc"), reply_markup=loc_kb(lang))
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
    lang = (await state.get_data()).get("lang") or "az"
    await message.answer(t(lang, "bio"), reply_markup=ReplyKeyboardRemove())
    await state.set_state(Reg.bio)


@router.message(Reg.loc)
async def reg_loc_bad(message: Message) -> None:
    await message.answer("Konum düyməsindən göndər.", reply_markup=loc_kb("az"))


@router.message(Reg.bio)
async def reg_bio(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "/skip":
        text = ""
    if len(text) > 300:
        await message.answer("300 simvoldan qısa.")
        return
    await state.update_data(bio=text)
    lang = (await state.get_data()).get("lang") or "az"
    await message.answer(t(lang, "photo"))
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
    await db.set_field(message.from_user.id, "lang", data.get("lang") or "az")
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
    try:
        await bot.send_message(OWNER_ID, "Yeni müştəri qoşuldu. Yuxarıdakı anketə bax və təsdiqlə.")
    except Exception:
        logging.exception("owner ping failed")


@router.message(Reg.photo)
async def reg_photo_bad(message: Message) -> None:
    await message.answer("Şəkil göndər.")


@router.message(F.text.in_(MENU_FEED))
async def feed(message: Message) -> None:
    if await gate(message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Bu gecə Bakı", callback_data="night:Bakı"),
             InlineKeyboardButton(text="Bu gecə Gəncə", callback_data="night:Gəncə")],
        ])
        await message.answer("Yaxın lent. Cümə axşamı Bakı və Gəncə gecələri ayrıca seçilir.", reply_markup=kb)
        await show_next(message, message.from_user.id)


@router.callback_query(F.data.startswith("night:"))
async def night(cb: CallbackQuery) -> None:
    city = cb.data.split(":", 1)[1]
    me = await db.get(cb.from_user.id)
    if not me or me["status"] != "approved":
        await cb.answer(NOT_APPROVED, show_alert=True)
        return
    row = await db.next_profile(me)
    found = None
    # one city pass
    me_city = dict(me)
    me_city["city_only"] = 1
    me_city["city"] = city
    class R(dict):
        def __getitem__(self, k):
            return dict.get(self, k)
    fake = R(me_city)
    found = await db.next_profile(fake)
    if not found:
        await cb.answer(f"{city} gecəsində yeni anket yoxdur.", show_alert=True)
        return
    await cb.answer()
    await send_card(cb.message, found, me)


@router.message(F.text.in_(MENU_PROFILE))
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
        [InlineKeyboardButton(text="1 gün gizlət", callback_data="e:day")],
        [InlineKeyboardButton(text="Yalnız şəhərim", callback_data="e:cityonly")],
        [InlineKeyboardButton(text="Dil", callback_data="e:lang")],
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


@router.callback_query(F.data == "e:day")
async def hide_day(cb: CallbackQuery) -> None:
    until = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    await db.set_field(cb.from_user.id, "hidden_until", until)
    await cb.answer("24 saat görünməyəcəksən. Anket silinmədi.", show_alert=True)


@router.callback_query(F.data == "e:cityonly")
async def city_only(cb: CallbackQuery) -> None:
    row = await db.get(cb.from_user.id)
    new = 0 if row["city_only"] else 1
    await db.set_field(cb.from_user.id, "city_only", new)
    await cb.answer("Yalnız şəhərin." if new else "Bütün şəhərlər.", show_alert=True)


@router.callback_query(F.data == "e:lang")
async def lang_menu(cb: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="AZ", callback_data="setlang:az"),
        InlineKeyboardButton(text="RU", callback_data="setlang:ru"),
        InlineKeyboardButton(text="EN", callback_data="setlang:en"),
    ]])
    await cb.message.answer("Dili seç.", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("setlang:"))
async def set_lang(cb: CallbackQuery) -> None:
    lang = cb.data.split(":")[1]
    await db.set_field(cb.from_user.id, "lang", lang)
    await cb.message.answer(t(lang, "back").format(name=" ", status=t(lang, "st_ok")), reply_markup=main_kb(cb.from_user.id, lang))
    await cb.answer()


@router.callback_query(F.data.startswith("e:"))
async def edit_start(cb: CallbackQuery, state: FSMContext) -> None:
    field = cb.data.split(":")[1]
    if field in ("hide", "ref", "day", "cityonly", "lang"):
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


@router.message(F.text.in_(MENU_LOC))
async def ask_loc(message: Message, state: FSMContext) -> None:
    await state.set_state(Reg.loc)
    await state.update_data(only_loc=True)
    await message.answer(ASK_LOC, reply_markup=loc_kb("az"))


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
    await cb.answer("Getdi.")
    if action == "like" and not matched:
        await cb.message.answer("Bəyəndin. Qarşı tərəf də bəyənsə, yazacam. İndilik adı gizlidir.")
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
        ice = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Sakit və xoş gəldi", callback_data=f"ice:0:{to_id}")],
            [InlineKeyboardButton(text="Çay vaxtın varsa yaz", callback_data=f"ice:1:{to_id}")],
            [InlineKeyboardButton(text="Yaxınıq, bir salam", callback_data=f"ice:2:{to_id}")],
            [InlineKeyboardButton(text="Yaz", url=f"https://t.me/{other['username']}" if other["username"] else f"tg://user?id={to_id}")],
        ])
        await cb.message.answer(body + "\n\nAd indi açıqdır. İsti cümləni seç, mən ötürərəm.", reply_markup=ice)
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


ICE = [
    "Salam. Anketin sakit və xoş gəldi.",
    "Çay içməyə vaxtın varsa, yaz.",
    "Yaxınlıqdayıq. Bir salam de, görüm.",
]


@router.callback_query(F.data.startswith("ice:"))
async def ice(cb: CallbackQuery, bot: Bot) -> None:
    _, idx, uid = cb.data.split(":")
    text = ICE[int(idx)]
    me = await db.get(cb.from_user.id)
    try:
        await bot.send_message(int(uid), f"{me['name']} yazdı:\n{text}")
    except Exception:
        await cb.answer("Çatmadı, profil bağlı ola bilər.", show_alert=True)
        return
    await cb.answer("Göndərdim.")
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
        f"Şikayət\nHədəf: <code>{uid}</code>\nSəbəb: {reason}\nÜmumi şikayət: {n}\n"
        + ("3 şikayət — avtomatik yoxlamaya düşdü.\n" if n >= 3 else "")
        + f"Göndərən: <code>{cb.from_user.id}</code>",
        kb=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Ban", callback_data=f"adm:ban:{uid}"),
            InlineKeyboardButton(text="Aç", callback_data=f"adm:open:{uid}"),
        ]]),
    )
    await show_next(cb.message, cb.from_user.id)


@router.message(F.text.in_(MENU_MATCH))
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


@router.message(F.text.in_(MENU_LIKES))
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


@router.message(F.text.in_(MENU_PAY))
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
async def paid(message: Message, bot: Bot) -> None:
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
    row = await db.get(uid)
    await notify_admins(bot, f"Ödəniş: {row['name'] if row else uid} · {kind} · {stars} Stars · id {uid}")


@router.message(F.text.in_({"🛠 Admin panel", "Admin", "admin"}))
@router.message(Command("admin"))
@router.message(Command("panel"))
async def admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Bu panel yalnız admin üçündür.")
        return
    total, pending, approved, banned = await db.counts()
    wait = await db.setting("wait_mode", "1")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Gözləyənlər", callback_data="adm:list")],
        [InlineKeyboardButton(text="Şikayətlər", callback_data="adm:reps")],
        [InlineKeyboardButton(text="Hamıya", callback_data="adm:cast:all")],
        [InlineKeyboardButton(text="Yalnız Bakı", callback_data="adm:cast:baki")],
        [InlineKeyboardButton(text="Yalnız oğlan", callback_data="adm:cast:oglan")],
        [InlineKeyboardButton(text="Yalnız qız", callback_data="adm:cast:qiz")],
        [InlineKeyboardButton(text="100-ü təsdiqlə", callback_data="adm:bulk")],
        [InlineKeyboardButton(text=f"Gözləmə rejimi: {wait}", callback_data="adm:wait")],
    ])
    await message.answer(
        f"İstifadəçi: {total}\nGözləyən: {pending}\nTəsdiqli: {approved}\nBan: {banned}\n\n"
        "Axtarış: /user 123456\nBan: /ban 123\nAç: /unban 123\nPremium: /grant 123\nQeyd: /qeyd 123 mətn\nHəftənin anketi: /hefte 123",
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
        target = parts[2] if len(parts) > 2 else "all"
        await state.set_state(Cast.text)
        await state.update_data(target=target)
        await cb.message.answer(f"Mesaj yaz. Hədəf: {target}. Ləğv: /cancel")
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
        await db.blacklist(uid, "admin")
        try:
            await bot.send_message(uid, BANNED)
        except Exception:
            pass
        await cb.answer("Ban və qara siyahı.")
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
    target = (await state.get_data()).get("target", "all")
    if target == "baki":
        ids = await db.ids_for(city="Bakı")
    elif target in ("oglan", "qiz"):
        ids = await db.ids_for(gender=target)
    else:
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
        f"Ödəniş: {pay_s}\nAdmin qeydi: {row['admin_note'] or '—'}"
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
    await db.blacklist(uid, "admin")
    try:
        await bot.send_message(uid, BANNED)
    except Exception:
        pass
    await message.answer("Ban olundu və qara siyahıya düşdü.")


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


@router.message(F.sticker)
async def save_sticker(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    key = (message.caption or "hi").strip().lower()
    if key not in ("hi", "match", "super", "wait"):
        key = "hi"
    await db.set_setting(f"sticker:{key}", message.sticker.file_id)
    await message.answer(f"Stiker yazıldı: {key}. İndi bot bunu göndərəcək.")


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


@router.message(Command("qeyd"))
async def note_cmd(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("/qeyd 123 şübhəli şəkil")
        return
    await db.set_field(int(parts[1]), "admin_note", parts[2])
    await message.answer("Qeyd yazıldı. Müştəri görmür.")


@router.message(Command("hefte"))
async def week_cmd(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("/hefte 123456")
        return
    await db.set_setting("featured", parts[1])
    await message.answer("Həftənin anketi lentin başına qoyuldu.")


async def jobs(bot: Bot) -> None:
    while True:
        try:
            hour = datetime.now(timezone.utc).hour
            if hour == 16 and await db.setting("night_ping", "") != today():
                await db.set_setting("night_ping", today())
                for uid in await db.approved_ids():
                    try:
                        await bot.send_message(uid, "Axşam lentidir, 20:00–23:00. Yaxınlığa bir bax. 💛")
                    except Exception:
                        pass
                    await asyncio.sleep(0.04)
            if hour == 17 and await db.setting("summary_day", "") != today():
                await db.set_setting("summary_day", today())
                new, approved, reports, pay_n, stars = await db.day_stats()
                await notify_admins(bot, f"Günlük xülasə\nYeni: {new}\nTəsdiq: {approved}\nŞikayət: {reports}\nÖdəniş: {pay_n} · {stars} Stars")
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
    try:
        await bot.send_message(OWNER_ID, "Bot işləyir. Panel üçün /admin və ya 🛠 Admin panel.")
    except Exception:
        logging.exception("startup ping failed")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
