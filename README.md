# SazDating

Telegram tanışlıq botu. Konum, yaxın anket, Stars ödənişi, admin təsdiqi.

## Railway — addım-addım

1. Telefonda Telegram aç. Axtar: `@BotFather`. `/newbot` yaz. Ad: SazDating. Username: `sazdatingbot` (tutulubsa başqa sonluq). Tokeni kopyala, kimə göndərmə.
2. Öz id-in: `@userinfobot` → `/start` → rəqəmi kopyala.
3. Kompüterdə https://github.com aç, hesab yarat, New repository, ad `sazdating`, Private, Create.
4. Bu qovluqdakı faylları ora yüklə: Add file → Upload files. `bot.py`, `db.py`, `texts.py`, `requirements.txt`, `Procfile`, `railway.toml`, `.env.example`. Commit.
5. https://railway.app aç. Login with GitHub.
6. New Project → Deploy from GitHub repo → `sazdating`.
7. Açılan servisdə Variables:
   - `BOT_TOKEN` = BotFather tokeni
   - `ADMIN_IDS` = sənin rəqəm id-in
   - `DB_PATH` = `sazdating.db`
8. Deploy. Logs-da `Run polling` görünsə işləyir.
9. Telegramda bota `/start`.

Qeyd: pulsuz Railway yuxuya gedə bilər. Daimi iş üçün Hobby plan, və ya servis növü Worker olsun, web port axtarmasın. Start command: `python bot.py`.

BotFather → bot → Payments → Telegram Stars aktiv olsun.

## Qaydalar

- 18-dən aşağı qeydiyyat dayanır.
- Anket admin təsdiqinə düşür. Gözləmə rejimi açıqdır: 100 nəfər yığılana qədər təsdiq düyməsi xəbərdarlıq edir. Admin paneldə rejimi söndürüb tək-tək və ya «100-ü təsdiqlə» ilə aça bilərsən.
- Təsdiqli ad: mavi tik. Premium: sarı tik.
- Pulsuz gündə 30 bəyənmə. +30 = 100 Stars. 1 superlike = 25 Stars. Premium 7 gün = 1000 Stars, limitsiz bəyənmə, gündə 20 superlike.
- Superlike qarşı tərəfə ayrı kartla gəlir: «Sənə superlike gəldi».
- Hər gün 18:00 Bakı vaxtı qısa dəvət mesajı.
- Premium bitməsinə 5–1 saat qalanda xəbərdarlıq.

## Admin

Düymə: Admin. Əmrlər: `/user ID`, `/ban ID`, `/unban ID`, `/grant ID`.
