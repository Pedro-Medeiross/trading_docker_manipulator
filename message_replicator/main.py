import os
import re
from telethon import TelegramClient, events
from dotenv import load_dotenv

# Carrega o .env dentro do container
load_dotenv()

# ---------------- Env helpers ----------------
def get_env_var(key, cast_func=str):
    val = os.getenv(key)
    if val is None:
        raise RuntimeError(f"❌ Variável de ambiente {key} não encontrada!")
    try:
        return cast_func(val)
    except Exception:
        raise RuntimeError(f"❌ Variável {key} inválida para cast {cast_func.__name__}.")

API_ID = get_env_var("API_ID", int)
API_HASH = get_env_var("API_HASH")

FROM_CHAT_AVALON = get_env_var("FROM_CHAT_AVALON", int)
TO_CHAT_AVALON   = get_env_var("TO_CHAT_AVALON", int)

FROM_CHAT_POLARIUM = get_env_var("FROM_CHAT_POLARIUM", int)
TO_CHAT_POLARIUM   = get_env_var("TO_CHAT_POLARIUM", int)

FROM_CHAT_XOFRE = get_env_var("FROM_CHAT_XOFRE", int)
TO_CHAT_XOFRE   = get_env_var("TO_CHAT_XOFRE", int)

FROM_CHAT_HOME_BROKER = get_env_var("FROM_CHAT_HOME_BROKER", int)
TO_CHAT_HOME_BROKER   = get_env_var("TO_CHAT_HOME_BROKER", int)

# Encaminhar tudo? (padrão: False -> filtra pelos formatos novos)
FORWARD_ALL = os.getenv("FORWARD_ALL", "false").strip().lower() in ("1","true","yes","y")

print(f'api_id: {API_ID} api_hash: {API_HASH}')
print(f'avalon:   from={FROM_CHAT_AVALON} to={TO_CHAT_AVALON}')
print(f'polarium: from={FROM_CHAT_POLARIUM} to={TO_CHAT_POLARIUM}')
print(f'xofre:    from={FROM_CHAT_XOFRE} to={TO_CHAT_XOFRE}')
print(f'home_brk: from={FROM_CHAT_HOME_BROKER} to={TO_CHAT_HOME_BROKER}')
print(f'forward_all: {FORWARD_ALL}')

# ---------------- Filtros de conteúdo ----------------
_re_entry = re.compile(r"(?is)\bNOVA\s+ENTRADA\b.*?\bPar\s*:\s*([A-Z/]{6,12}).*?\bTimeframe\s*:\s*(1|5)\b.*?\bDire[cç][aã]o\s*:\s*(BUY|SELL)\b")
_re_result = re.compile(r"(?is)\bRESULTADO\s*:\s*(WIN|LOSS)\b")

def is_relevant_text(text: str) -> bool:
    if FORWARD_ALL:
        return True
    if not text:
        return False
    return bool(_re_entry.search(text) or _re_result.search(text))

# ---------------- Client ----------------
client = TelegramClient('user_session', API_ID, API_HASH)

async def _forward_if_relevant(event, dest_name: str, dest_chat: int):
    msg_obj = event.message
    text = getattr(msg_obj, "message", None)

    if not FORWARD_ALL:
        if not text or not is_relevant_text(text):
            print(f"ℹ️ [{dest_name}] Ignorado (não bate com os formatos novos).")
            return

    try:
        print(f"📥 [{dest_name}] Mensagem recebida de {event.chat_id}")
        # Encaminha preservando conteúdo original (markup, mídia, etc.)
        await client.forward_messages(dest_chat, msg_obj)
        print(f"📤 [{dest_name}] Mensagem encaminhada com sucesso.")
    except Exception as e:
        print(f"❌ [{dest_name}] Erro ao encaminhar: {e}")

# ---------------- Handlers ----------------
@client.on(events.NewMessage(chats=FROM_CHAT_AVALON))
async def handler_avalon(event):
    await _forward_if_relevant(event, "AVALON", TO_CHAT_AVALON)

@client.on(events.NewMessage(chats=FROM_CHAT_POLARIUM))
async def handler_polarium(event):
    await _forward_if_relevant(event, "POLARIUM", TO_CHAT_POLARIUM)

@client.on(events.NewMessage(chats=FROM_CHAT_XOFRE))
async def handler_xofre(event):
    await _forward_if_relevant(event, "XOFRE", TO_CHAT_XOFRE)

@client.on(events.NewMessage(chats=FROM_CHAT_HOME_BROKER))
async def handler_home_broker(event):
    await _forward_if_relevant(event, "HOME_BROKER", TO_CHAT_HOME_BROKER)

print("🤖 Bot com Telethon iniciado... aguardando mensagens.")
client.start()
client.run_until_disconnected()
