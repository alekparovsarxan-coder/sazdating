import math
import os
from datetime import datetime, timedelta, timezone

import aiosqlite

BAKU = timezone(timedelta(hours=4))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    age INTEGER,
    gender TEXT,
    looking TEXT,
    city TEXT,
    bio TEXT,
    photo_id TEXT,
    lat REAL,
    lon REAL,
    status TEXT DEFAULT 'pending',
    is_premium INTEGER DEFAULT 0,
    premium_until TEXT,
    likes_today INTEGER DEFAULT 0,
    likes_day TEXT,
    extra_likes INTEGER DEFAULT 0,
    super_credits INTEGER DEFAULT 0,
    super_today INTEGER DEFAULT 0,
    super_day TEXT,
    likes_sent INTEGER DEFAULT 0,
    super_sent INTEGER DEFAULT 0,
    likes_recv INTEGER DEFAULT 0,
    super_recv INTEGER DEFAULT 0,
    complaints INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    referrer INTEGER,
    created_at TEXT,
    approved_at TEXT,
    last_nudge TEXT,
    like_warn TEXT,
    prem_warn TEXT
);
CREATE TABLE IF NOT EXISTS swipes (
    from_id INTEGER,
    to_id INTEGER,
    action TEXT,
    created_at TEXT,
    PRIMARY KEY (from_id, to_id)
);
CREATE TABLE IF NOT EXISTS matches (
    user_a INTEGER,
    user_b INTEGER,
    created_at TEXT,
    PRIMARY KEY (user_a, user_b)
);
CREATE TABLE IF NOT EXISTS blocks (
    user_id INTEGER,
    blocked_id INTEGER,
    PRIMARY KEY (user_id, blocked_id)
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER,
    to_id INTEGER,
    reason TEXT,
    created_at TEXT,
    open INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    kind TEXT,
    stars INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS blacklist (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    created_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def today() -> str:
    return datetime.now(BAKU).date().isoformat()


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class DB:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('wait_mode', '0')"
            )
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('min_users', '100')"
            )
            for col, kind in (
                ("lang", "TEXT"), ("city_only", "INTEGER"), ("hidden_until", "TEXT"),
                ("admin_note", "TEXT"), ("phone", "TEXT"), ("boost_day", "TEXT"),
                ("last_seen", "TEXT"), ("photo_uid", "TEXT"), ("views_today", "INTEGER"),
                ("views_day", "TEXT"), ("bday", "TEXT"), ("campaign", "TEXT"), ("coins", "INTEGER"),
            ):
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {kind}")
                except Exception:
                    pass
            await db.commit()

    async def get(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            return await cur.fetchone()

    async def setting(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def save_profile(self, data: dict) -> None:
        data = {**data, "created_at": now(), "status": "pending"}
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (
                    user_id, username, name, age, gender, looking, city, bio, photo_id,
                    lat, lon, status, referrer, created_at
                ) VALUES (
                    :user_id, :username, :name, :age, :gender, :looking, :city, :bio, :photo_id,
                    :lat, :lon, :status, :referrer, :created_at
                )
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username, name=excluded.name, age=excluded.age,
                    gender=excluded.gender, looking=excluded.looking, city=excluded.city,
                    bio=excluded.bio, photo_id=excluded.photo_id, lat=excluded.lat,
                    lon=excluded.lon, status='pending', approved_at=NULL
                """,
                data,
            )
            await db.commit()

    async def set_field(self, user_id: int, field: str, value) -> None:
        allowed = {
            "name", "age", "city", "bio", "looking", "username", "photo_id",
            "lat", "lon", "hidden", "status", "approved_at", "last_nudge",
            "like_warn", "prem_warn", "lang", "city_only", "hidden_until", "admin_note", "phone",
            "boost_day", "last_seen", "photo_uid", "views_today", "views_day", "bday", "campaign", "is_premium",
        }
        if field not in allowed:
            raise ValueError(field)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
            await db.commit()

    def is_premium(self, row) -> bool:
        if not row or not row["is_premium"] or not row["premium_until"]:
            return False
        return datetime.fromisoformat(row["premium_until"]) > datetime.now(timezone.utc)

    def tick(self, row) -> str:
        if self.is_premium(row):
            return " ⭐"
        if row["status"] == "approved":
            return " ✅"
        return ""

    async def grant_premium(self, user_id: int, days: int) -> str:
        base = datetime.now(timezone.utc)
        row = await self.get(user_id)
        if row and self.is_premium(row):
            base = datetime.fromisoformat(row["premium_until"])
        until = base + timedelta(days=days)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?",
                (until.isoformat(), user_id),
            )
            await db.commit()
            if cur.rowcount < 1:
                return ""
        return until.astimezone(BAKU).strftime("%d.%m.%Y %H:%M")

    async def add_extra_likes(self, user_id: int, n: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET extra_likes=extra_likes+? WHERE user_id=?", (n, user_id)
            )
            await db.commit()

    async def gifted(self, user_id: int) -> bool:
        return await self.setting(f"gift:{user_id}", "") == "1"

    async def gift_once(self, user_id: int, phone: str | None) -> bool:
        if await self.gifted(user_id):
            return False
        if phone and await self.setting(f"giftphone:{phone}", "") == "1":
            return False
        await self.add_coins(user_id, 35)
        await self.set_setting(f"gift:{user_id}", "1")
        if phone:
            await self.set_setting(f"giftphone:{phone}", "1")
        return True

    async def add_coins(self, user_id: int, n: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET coins=COALESCE(coins,0)+? WHERE user_id=?", (n, user_id)
            )
            await db.commit()
        row = await self.get(user_id)
        return row["coins"] or 0

    async def spend_coins(self, user_id: int, n: int) -> bool:
        row = await self.get(user_id)
        have = (row["coins"] or 0) if row else 0
        if have < n:
            return False
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET coins=coins-? WHERE user_id=?", (n, user_id))
            await db.commit()
        return True

    async def find_phone(self, phone: str):
        digits = "".join(ch for ch in phone if ch.isdigit())
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE phone LIKE ?", (f"%{digits[-9:]}%",))
            return await cur.fetchone()

    async def add_super(self, user_id: int, n: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET super_credits=super_credits+? WHERE user_id=?", (n, user_id)
            )
            await db.commit()

    async def log_payment(self, user_id: int, kind: str, stars: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO payments (user_id, kind, stars, created_at) VALUES (?,?,?,?)",
                (user_id, kind, stars, now()),
            )
            await db.commit()

    async def likes_left(self, row) -> int | None:
        if self.is_premium(row):
            return None
        used = row["likes_today"] if row["likes_day"] == today() else 0
        return max(0, 30 - used) + (row["extra_likes"] or 0)

    async def consume_like(self, user_id: int) -> bool:
        row = await self.get(user_id)
        if self.is_premium(row):
            return True
        day = today()
        used = row["likes_today"] if row["likes_day"] == day else 0
        extra = row["extra_likes"] or 0
        if used < 30:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "UPDATE users SET likes_today=?, likes_day=? WHERE user_id=?",
                    (used + 1, day, user_id),
                )
                await db.commit()
            return True
        if extra > 0:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "UPDATE users SET extra_likes=extra_likes-1 WHERE user_id=?", (user_id,)
                )
                await db.commit()
            return True
        return False

    async def consume_super(self, user_id: int) -> str:
        """ok | need_credit | premium_limit"""
        row = await self.get(user_id)
        day = today()
        if self.is_premium(row):
            used = row["super_today"] if row["super_day"] == day else 0
            if used >= 20:
                return "premium_limit"
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "UPDATE users SET super_today=?, super_day=? WHERE user_id=?",
                    (used + 1, day, user_id),
                )
                await db.commit()
            return "ok"
        if (row["super_credits"] or 0) < 1:
            return "need_credit"
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET super_credits=super_credits-1 WHERE user_id=?", (user_id,)
            )
            await db.commit()
        return "ok"

    async def next_profile(self, me):
        uid = me["user_id"]
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            q = """
                SELECT * FROM users
                WHERE user_id != ?
                  AND status='approved'
                  AND hidden=0
                  AND photo_id IS NOT NULL
                  AND user_id NOT IN (SELECT to_id FROM swipes WHERE from_id=?)
                  AND user_id NOT IN (SELECT blocked_id FROM blocks WHERE user_id=?)
                  AND ? NOT IN (SELECT blocked_id FROM blocks WHERE user_id=users.user_id)
            """
            args: list = [uid, uid, uid, uid]
            if me["looking"] and me["looking"] != "hami":
                q += " AND gender=?"
                args.append(me["looking"])
            if me["city_only"]:
                q += " AND city=?"
                args.append(me["city"])
            cur = await db.execute(q, args)
            rows = await cur.fetchall()
        now_iso = now()
        rows = [r for r in rows if not r["hidden_until"] or r["hidden_until"] < now_iso]
        rows = [r for r in rows if not r["last_seen"] or r["last_seen"] > (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()]
        if not rows:
            return None
        featured = await self.setting("featured", "")
        for r in rows:
            if featured and str(r["user_id"]) == featured:
                return r

        def score(r):
            dist = 99999.0
            if me["lat"] and r["lat"]:
                dist = haversine(me["lat"], me["lon"], r["lat"], r["lon"])
            if dist <= 15:
                band = 0
            elif dist <= 40:
                band = 1
            elif dist <= 100:
                band = 2
            else:
                band = 3
            same = 0 if r["city"] == me["city"] else 1
            lang = 0 if (r["lang"] or "az") == (me["lang"] or "az") else 1
            stale = 1 if r["last_seen"] and r["last_seen"] < (datetime.now(timezone.utc) - timedelta(days=14)).isoformat() else 0
            boost = 0 if r["boost_day"] == today() else 1
            prem = 0 if self.is_premium(r) else 1
            return (boost, band, lang, same, stale, prem, dist)

        rows = sorted(rows, key=score)
        return rows[0]

    async def swipe(self, from_id: int, to_id: int, action: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO swipes (from_id, to_id, action, created_at) VALUES (?,?,?,?)",
                (from_id, to_id, action, now()),
            )
            if action == "like":
                await db.execute("UPDATE users SET likes_sent=likes_sent+1 WHERE user_id=?", (from_id,))
                await db.execute("UPDATE users SET likes_recv=likes_recv+1 WHERE user_id=?", (to_id,))
            if action == "super":
                await db.execute("UPDATE users SET super_sent=super_sent+1 WHERE user_id=?", (from_id,))
                await db.execute("UPDATE users SET super_recv=super_recv+1 WHERE user_id=?", (to_id,))
            match = False
            if action in ("like", "super"):
                cur = await db.execute(
                    "SELECT 1 FROM swipes WHERE from_id=? AND to_id=? AND action IN ('like','super')",
                    (to_id, from_id),
                )
                if await cur.fetchone():
                    a, b = sorted((from_id, to_id))
                    await db.execute(
                        "INSERT OR IGNORE INTO matches (user_a, user_b, created_at) VALUES (?,?,?)",
                        (a, b, now()),
                    )
                    match = True
            await db.execute("UPDATE users SET views=views+1 WHERE user_id=?", (to_id,))
            await db.execute(
                "UPDATE users SET views_today=COALESCE(views_today,0)+1, views_day=? WHERE user_id=?",
                (today(), to_id),
            )
            await db.commit()
            return match

    async def last_skip(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT s.to_id, u.* FROM swipes s
                JOIN users u ON u.user_id=s.to_id
                WHERE s.from_id=? AND s.action='skip'
                ORDER BY s.created_at DESC LIMIT 1
                """,
                (user_id,),
            )
            return await cur.fetchone()

    async def undo_skip(self, user_id: int, to_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM swipes WHERE from_id=? AND to_id=? AND action='skip'",
                (user_id, to_id),
            )
            await db.commit()

    async def likes_received(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT u.*, s.action FROM swipes s
                JOIN users u ON u.user_id=s.from_id
                WHERE s.to_id=? AND s.action IN ('like','super')
                  AND NOT EXISTS (
                    SELECT 1 FROM swipes b WHERE b.from_id=? AND b.to_id=s.from_id
                  )
                ORDER BY CASE s.action WHEN 'super' THEN 0 ELSE 1 END, s.created_at DESC
                LIMIT 30
                """,
                (user_id, user_id),
            )
            return await cur.fetchall()

    async def my_matches(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT u.* FROM matches m
                JOIN users u ON u.user_id = CASE WHEN m.user_a=? THEN m.user_b ELSE m.user_a END
                WHERE m.user_a=? OR m.user_b=?
                ORDER BY m.created_at DESC LIMIT 30
                """,
                (user_id, user_id, user_id),
            )
            return await cur.fetchall()

    async def block(self, user_id: int, blocked_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO blocks (user_id, blocked_id) VALUES (?,?)",
                (user_id, blocked_id),
            )
            a, b = sorted((user_id, blocked_id))
            await db.execute("DELETE FROM matches WHERE user_a=? AND user_b=?", (a, b))
            await db.commit()

    async def report(self, from_id: int, to_id: int, reason: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO reports (from_id, to_id, reason, created_at, open) VALUES (?,?,?,?,1)",
                (from_id, to_id, reason, now()),
            )
            await db.execute(
                "UPDATE users SET complaints=complaints+1 WHERE user_id=?", (to_id,)
            )
            cur = await db.execute("SELECT complaints FROM users WHERE user_id=?", (to_id,))
            n = (await cur.fetchone())[0]
            if n >= 3:
                await db.execute("UPDATE users SET status='pending' WHERE user_id=?", (to_id,))
            await db.commit()
            return n

    async def set_status(self, user_id: int, status: str) -> None:
        approved = now() if status == "approved" else None
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET status=?, approved_at=? WHERE user_id=?",
                (status, approved, user_id),
            )
            await db.commit()

    async def pending(self, limit: int = 10):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM users WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            return await cur.fetchall()

    async def open_reports(self, limit: int = 15):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT r.*, u.name, u.complaints FROM reports r
                LEFT JOIN users u ON u.user_id=r.to_id
                WHERE r.open=1 ORDER BY r.id DESC LIMIT ?
                """,
                (limit,),
            )
            return await cur.fetchall()

    async def close_report(self, report_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE reports SET open=0 WHERE id=?", (report_id,))
            await db.commit()

    async def counts(self):
        async with aiosqlite.connect(self.path) as db:
            total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
            pending = (await (await db.execute("SELECT COUNT(*) FROM users WHERE status='pending'")).fetchone())[0]
            approved = (await (await db.execute("SELECT COUNT(*) FROM users WHERE status='approved'")).fetchone())[0]
            banned = (await (await db.execute("SELECT COUNT(*) FROM users WHERE status='banned'")).fetchone())[0]
            return total, pending, approved, banned

    async def gender_counts(self):
        async with aiosqlite.connect(self.path) as db:
            boys = (await (await db.execute("SELECT COUNT(*) FROM users WHERE gender='oglan'")).fetchone())[0]
            girls = (await (await db.execute("SELECT COUNT(*) FROM users WHERE gender='qiz'")).fetchone())[0]
            return boys, girls

    async def search_name(self, q: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE name LIKE ? LIMIT 15", (f"%{q}%",))
            return await cur.fetchall()

    async def search_city(self, q: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE city LIKE ? LIMIT 15", (f"%{q}%",))
            return await cur.fetchall()

    async def dup_photos(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT photo_uid, COUNT(*) n FROM users
                WHERE photo_uid IS NOT NULL AND photo_uid != ''
                GROUP BY photo_uid HAVING n>1 LIMIT 10
                """
            )
            return await cur.fetchall()

    async def approved_ids(self):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE status='approved'")
            return [r[0] for r in await cur.fetchall()]

    async def all_ids(self):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE status!='banned'")
            return [r[0] for r in await cur.fetchall()]

    async def nudge_candidates(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM users WHERE status='approved' AND (last_nudge IS NULL OR last_nudge!=?)",
                (today(),),
            )
            return await cur.fetchall()

    async def mark_nudge(self, user_id: int) -> None:
        await self.set_field(user_id, "last_nudge", today())

    async def expiring_premium(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM users WHERE is_premium=1 AND premium_until IS NOT NULL AND status='approved'"
            )
            return await cur.fetchall()

    async def blacklist(self, user_id: int, reason: str = "ban") -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO blacklist (user_id, reason, created_at) VALUES (?,?,?)",
                (user_id, reason, now()),
            )
            await db.execute("UPDATE users SET admin_note=? WHERE user_id=?", (reason, user_id))
            await db.commit()

    async def same_photo(self, photo_uid: str, user_id: int):
        if not photo_uid:
            return None
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT user_id, status, name FROM users WHERE photo_uid=? AND user_id!=?",
                (photo_uid, user_id),
            )
            return await cur.fetchone()

    async def is_blacklisted(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT 1 FROM blacklist WHERE user_id=?", (user_id,))
            return bool(await cur.fetchone())

    async def ids_for(self, city: str | None = None, gender: str | None = None):
        q = "SELECT user_id FROM users WHERE status='approved'"
        args = []
        if city:
            q += " AND city=?"
            args.append(city)
        if gender:
            q += " AND gender=?"
            args.append(gender)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(q, args)
            return [r[0] for r in await cur.fetchall()]

    async def day_stats(self):
        day = today()
        async with aiosqlite.connect(self.path) as db:
            new = (await (await db.execute("SELECT COUNT(*) FROM users WHERE created_at LIKE ?", (day + "%",))).fetchone())[0]
            approved = (await (await db.execute("SELECT COUNT(*) FROM users WHERE approved_at LIKE ?", (day + "%",))).fetchone())[0]
            reports = (await (await db.execute("SELECT COUNT(*) FROM reports WHERE created_at LIKE ?", (day + "%",))).fetchone())[0]
            pays = (await (await db.execute("SELECT COUNT(*), COALESCE(SUM(stars),0) FROM payments WHERE created_at LIKE ?", (day + "%",))).fetchone())
            return new, approved, reports, pays[0], pays[1]

    async def payments_of(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 8", (user_id,)
            )
            return await cur.fetchall()
