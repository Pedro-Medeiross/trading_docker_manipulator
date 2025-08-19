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
# Aceita pares com -, ex.: EURUSD-OTC, e timeframe em vários formatos (1, 5, M1, 1m, 1 min)
_re_entry = re.compile(
    r"(?is)\bNOVA\s+ENTRADA\b"
    r".*?\bPar\s*:\s*([A-Z/\-]{6,20})"
    r".*?\bTime\s*frame\b|\bTimeframe\b",  # placeholder (será validado abaixo)
)

# Vamos validar timeframe/direção em funções separadas para logs melhores
_re_symbol = re.compile(r"(?is)\bPar\s*:\s*([A-Z/\-]{6,20})")
_re_timeframe = re.compile(
    r"(?is)\b(?:Time\s*frame|Timeframe)\s*:\s*(?:M?\s*([15])|([15])\s*m(?:in)?\b|([15])\b)"
)
_re_direction = re.compile(r"(?is)\bDire[cç][aã]o\s*:\s*(BUY|SELL)\b")

_re_result = re.compile(r"(?is)\bRESULTADO\s*:\s*(WIN|LOSS)\b")

def is_relevant_text(text: str) -> tuple[bool, str]:
    """Retorna (ok, motivo_ou_vazio)."""
    if FORWARD_ALL:
        return True, ""
    if not text:
        return False, "texto vazio"

    if not re.search(r"(?is)\bNOVA\s+ENTRADA\b", text) and not _re_result.search(text):
        return False, "não contém NOVA ENTRADA nem RESULTADO"

    # Se for resultado, já aceitamos
    if _re_result.search(text):
        return True, ""

    # Verificação granular para ENTRADA
    sm = _re_symbol.search(text)
    if not sm:
        return False, "sem Par:"
    symbol = sm.group(1).upper().replace("/", "")

    tfm = _re_timeframe.search(text)
    if not tfm:
        return False, "sem Timeframe válido"
    tf_digit = tfm.group(1) or tfm.group(2) or tfm.group(3)
    try:
        timeframe = int(tf_digit)
    except Exception:
        return False, "timeframe não numérico"
    if timeframe not in (1, 5):
        return False, f"timeframe fora de 1/5: {timeframe}"

    dm = _re_direction.search(text)
    if not dm:
        return False, "sem Direção"
    direction = dm.group(1).upper()
    if direction not in ("BUY", "SELL"):
        return False, f"direção inválida: {direction}"

    return True, ""

# ---------------- Client ----------------
client = TelegramClient('user_session', API_ID, API_HASH)

async def _forward_if_relevant(event, dest_name: str, dest_chat: int):
    msg_obj = event.message
    text = getattr(msg_obj, "message", None)

    if not FORWARD_ALL:
        ok, reason = is_relevant_text(text or "")
        if not ok:
            print(f"ℹ️ [{dest_name}] Ignorado: {reason}.")
            # log de depuração do conteúdo recebido
            if text:
                preview = text[:140].replace("\n", " ")
                print(f"   Conteúdo (preview): {preview}...")
            return

    try:
        print(f"📥 [{dest_name}] Mensagem recebida de chat_id={event.chat_id}")
        await client.forward_messages(dest_chat, msg_obj)
        print(f"📤 [{dest_name}] Mensagem encaminhada com sucesso -> {dest_chat}.")
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
