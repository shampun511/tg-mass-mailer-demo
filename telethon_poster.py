import os, asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "demo_session")

# Пример: рассылка одного текста и опционально одного media по списку чатов
TARGETS = [
    -1001234567890,   # id канала/супергруппы
    "username_or_link"
]
TEXT = "Демо-пост от юзер-аккаунта (Telethon)."
MEDIA_PATH = None  # например "banner.jpg" или None

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    async with client:
        for chat in TARGETS:
            try:
                if MEDIA_PATH:
                    await client.send_file(chat, MEDIA_PATH, caption=TEXT)
                else:
                    await client.send_message(chat, TEXT)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error sending to {chat}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
