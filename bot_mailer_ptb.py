import asyncio, os, csv
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import InputMediaPhoto, InputMediaVideo
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Простейшее "хранилище" в памяти (для демо)
DESTS = {}        # chat_id -> {"title": str, "categories": set}
CAMPAIGNS = {}    # cid -> {"text": str, "media": list[file_id], "cats": set}
LOGS = []         # [{"cid": int, "chat_id": str, "status": "ok"/"error", "error": str, "ts": iso}]

async def add_log(cid, chat_id, status, error=""):
    LOGS.append({
        "cid": cid, "chat_id": str(chat_id), "status": status,
        "error": error, "ts": datetime.utcnow().isoformat()
    })

def parse_cats(s: str):
    return set(x.strip() for x in s.split(",") if x.strip())

async def start(update, context):
    await update.message.reply_text(
        "Демо-рассыльщик (Bot API)\n"
        "/add_dest <chat_id> \"кат1,кат2\"\n"
        "/new <campaign_id> — ответь текстом/медиа и затем /save <campaign_id>\n"
        "/send_now <campaign_id> [\"кат1,кат2\"]\n"
        "/schedule_in <campaign_id> <минуты>\n"
        "/report <campaign_id>\n"
        "/export_csv — выгрузить логи"
    )

async def add_dest(update, context):
    if not context.args:
        return await update.message.reply_text("Использование: /add_dest <chat_id> \"кат1,кат2\"")
    chat_id = context.args[0]
    cats = parse_cats(" ".join(context.args[1:]).strip().strip('"').strip("'"))
    title = chat_id
    try:
        chat = await context.bot.get_chat(chat_id)
        title = chat.title or chat.username or str(chat.id)
    except Exception:
        pass
    DESTS[chat_id] = {"title": title, "categories": cats}
    await update.message.reply_text(f"Добавлено: {title} [{', '.join(cats) or 'без категорий'}]")

PENDING = {}  # user_id -> {"text": str, "media": list[file_id]}

async def new_campaign(update, context):
    if not context.args:
        return await update.message.reply_text("Использование: /new <campaign_id>")
    cid = context.args[0]
    PENDING[update.effective_user.id] = {"text": "", "media": []}
    await update.message.reply_text(
        f"Черновик кампании {cid}. Пришли текст и/или медиа. Когда готово — /save {cid}"
    )

async def cap_text(update, context):
    if update.effective_user.id in PENDING:
        prev = PENDING[update.effective_user.id]["text"]
        PENDING[update.effective_user.id]["text"] = (prev + "\n" if prev else "") + update.message.html_text

async def cap_media(update, context):
    if update.effective_user.id not in PENDING:
        return
    if update.message.photo:
        PENDING[update.effective_user.id]["media"].append(update.message.photo[-1].file_id)
    elif update.message.video:
        PENDING[update.effective_user.id]["media"].append(update.message.video.file_id)
    elif update.message.document:
        PENDING[update.effective_user.id]["media"].append(update.message.document.file_id)

async def save_campaign(update, context):
    if not context.args:
        return await update.message.reply_text("Использование: /save <campaign_id>")
    cid = context.args[0]
    draft = PENDING.pop(update.effective_user.id, None)
    if not draft:
        return await update.message.reply_text("Нет черновика. Сначала /new <campaign_id>.")
    CAMPAIGNS[cid] = {"text": draft["text"], "media": draft["media"], "cats": set()}
    await update.message.reply_text(f"Сохранено. /send_now {cid} или /schedule_in {cid} 15")

async def _send_campaign(context: ContextTypes.DEFAULT_TYPE, cid: str, only_cats=None):
    camp = CAMPAIGNS.get(cid)
    if not camp:
        return
    text, media = camp["text"], camp["media"]

    # Подготовим медиа-группу
    media_group = []
    for fid in media:
        # простая эвристика: если это фото или видео — PTB сам поймёт по file_id
        if fid.startswith("BAAC") or fid.startswith("AgAC"):  # не всегда работает; оставим общий путь
            media_group.append(InputMediaPhoto(fid))
        else:
            # попробуем как фото, при ошибке уйдёт в except
            media_group.append(InputMediaPhoto(fid))
    if media_group and text:
        media_group[0].caption = text
        media_group[0].parse_mode = ParseMode.HTML

    # таргеты: все или по категориям
    targets = []
    for chat_id, meta in DESTS.items():
        if not only_cats or meta["categories"].intersection(only_cats):
            targets.append(chat_id)

    for chat_id in targets:
        try:
            if media_group:
                await context.bot.send_media_group(chat_id=chat_id, media=media_group)
            elif text:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            else:
                raise ValueError("Пустая кампания")
            await add_log(cid, chat_id, "ok")
            await asyncio.sleep(0.4)
        except Exception as e:
            await add_log(cid, chat_id, "error", str(e))

async def send_now(update, context):
    if not context.args:
        return await update.message.reply_text("Использование: /send_now <campaign_id> [\"кат1,кат2\"]")
    cid = context.args[0]
    cats = parse_cats(" ".join(context.args[1:]).strip().strip('"').strip("'")) if len(context.args) > 1 else None
    await _send_campaign(context, cid, cats)
    await update.message.reply_text("Отправка завершена. Смотри /report.")

async def schedule_in(update, context):
    if len(context.args) < 2:
        return await update.message.reply_text("Использование: /schedule_in <campaign_id> <минуты>")
    cid = context.args[0]
    minutes = int(context.args[1])
    when = datetime.utcnow() + timedelta(minutes=minutes)
    context.job_queue.run_once(lambda ctx: asyncio.create_task(_send_campaign(ctx, cid)), when=when)
    await update.message.reply_text(f"Запланировано на {when.isoformat()} UTC")

async def report(update, context):
    if not context.args:
        return await update.message.reply_text("Использование: /report <campaign_id>")
    cid = context.args[0]
    ok = sum(1 for r in LOGS if r["cid"] == cid and r["status"] == "ok")
    err = sum(1 for r in LOGS if r["cid"] == cid and r["status"] == "error")
    await update.message.reply_text(f"Отчёт {cid} — OK: {ok}, ERR: {err}")

async def export_csv(update, context):
    fname = f"logs_{int(datetime.utcnow().timestamp())}.csv"
    with open(fname, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cid","chat_id","status","error","ts"])
        w.writeheader(); w.writerows(LOGS)
    await update.message.reply_document(document=fname, caption="Экспорт логов")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_dest", add_dest))
    app.add_handler(CommandHandler("new", new_campaign))
    app.add_handler(CommandHandler("save", save_campaign))
    app.add_handler(CommandHandler("send_now", send_now))
    app.add_handler(CommandHandler("schedule_in", schedule_in))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("export_csv", export_csv))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cap_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, cap_media))

    await app.initialize(); await app.start()
    await app.updater.start_polling(); await app.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
