from telethon import TelegramClient, events
import os
from dotenv import load_dotenv

# Carrega o .env dentro do container
#load_dotenv()

print("DEBUG - API_ID:", os.getenv("API_ID"))
print("DEBUG - API_HASH:", os.getenv("API_HASH"))

def get_env_var(key, cast_func=str):
    val = os.getenv(key)
    if val is None:
        raise RuntimeError(f"❌ Variável de ambiente {key} não encontrada!")
    return cast_func(val)

# Agora use as variáveis de forma segura:
API_ID = get_env_var("API_ID", int)
API_HASH = get_env_var("API_HASH")

FROM_CHAT_AVALON = get_env_var("FROM_CHAT_AVALON", int)
TO_CHAT_AVALON = get_env_var("TO_CHAT_AVALON", int)

FROM_CHAT_POLARIUM = get_env_var("FROM_CHAT_POLARIUM", int)
TO_CHAT_POLARIUM = get_env_var("TO_CHAT_POLARIUM", int)

FROM_CHAT_XOFRE = get_env_var("FROM_CHAT_XOFRE", int)
TO_CHAT_XOFRE = get_env_var("TO_CHAT_XOFRE", int)

print(f'api_id: {API_ID} api_hash: {API_HASH}')
print(f'chatso_avalon: {FROM_CHAT_AVALON} chatso_avalon: {TO_CHAT_AVALON}')
print(f'chatso_polarium: {FROM_CHAT_POLARIUM} chatso_polarium: {TO_CHAT_POLARIUM}')
print(f'chatso_xofre: {FROM_CHAT_XOFRE} chatso_xofre: {TO_CHAT_XOFRE}')

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
