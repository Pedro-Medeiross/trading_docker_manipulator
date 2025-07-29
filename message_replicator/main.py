import os
from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

FROM_CHAT_AVALON = int(os.getenv("FROM_CHAT_AVALON"))
TO_CHAT_AVALON = int(os.getenv("TO_CHAT_AVALON"))

FROM_CHAT_POLARIUM = int(os.getenv("FROM_CHAT_POLARIUM"))
TO_CHAT_POLARIUM = int(os.getenv("TO_CHAT_POLARIUM"))

FROM_CHAT_XOFRE = int(os.getenv("FROM_CHAT_XOFRE"))
TO_CHAT_XOFRE = int(os.getenv("TO_CHAT_XOFRE"))

client = TelegramClient('user_session', API_ID, API_HASH)


@client.on(events.NewMessage(chats=FROM_CHAT_AVALON))
async def handler_avalon(event):
    try:
        print(f"📥 [AVALON] Mensagem recebida de {FROM_CHAT_AVALON}")
        await client.send_message(TO_CHAT_AVALON, event.message)
        print("📤 [AVALON] Mensagem replicada com sucesso.")
    except Exception as e:
        print(f"❌ [AVALON] Erro ao replicar: {e}")


@client.on(events.NewMessage(chats=FROM_CHAT_POLARIUM))
async def handler_polarium(event):
    try:
        print(f"📥 [POLARIUM] Mensagem recebida de {FROM_CHAT_POLARIUM}")
        await client.send_message(TO_CHAT_POLARIUM, event.message)
        print("📤 [POLARIUM] Mensagem replicada com sucesso.")
    except Exception as e:
        print(f"❌ [POLARIUM] Erro ao replicar: {e}")


@client.on(events.NewMessage(chats=FROM_CHAT_XOFRE))
async def handler_xofre(event):
    try:
        print(f"📥 [XOFRE] Mensagem recebida de {FROM_CHAT_XOFRE}")
        await client.send_message(TO_CHAT_XOFRE, event.message)
        print("📤 [XOFRE] Mensagem replicada com sucesso.")
    except Exception as e:
        print(f"❌ [XOFRE] Erro ao replicar: {e}")


print("🤖 Bot com Telethon iniciado... aguardando mensagens.")
client.start()
client.run_until_disconnected()
