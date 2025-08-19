import os
import re
import json
import asyncio
import aio_pika
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()

TOKEN = os.getenv("TOKEN_TELEGRAM")
RABBITMQ_URL = os.getenv("RABBITMQ_URL")

async def send_to_queue(data):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    exchange = await channel.declare_exchange("polarium_signals", aio_pika.ExchangeType.FANOUT)

    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(data).encode(),
            delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT
        ),
        routing_key=""
    )

    await connection.close()

def _normalize_symbol(sym: str | None) -> str | None:
    if not sym:
        return None
    sym = sym.strip().upper()
    return sym.replace("/", "")

def _parse_entry(text: str):
    """
    Formato esperado:
    🚀 NOVA ENTRADA
    • Par: EURUSD
    • Timeframe: 1
    • Direção: BUY
    """
    if not re.search(r"(?i)\bNOVA\s+ENTRADA\b", text):
        return None

    # Par
    par_match = re.search(r"(?i)par\s*:\s*([A-Z/]{6,12})", text)
    symbol = _normalize_symbol(par_match.group(1)) if par_match else None

    # Timeframe (min)
    tf_match = re.search(r"(?i)time\s*frame\s*:\s*(\d+)|timeframe\s*:\s*(\d+)", text)
    timeframe = None
    if tf_match:
        tf_groups = [g for g in tf_match.groups() if g]
        if tf_groups:
            timeframe = int(tf_groups[0])

    # Direção
    dir_match = re.search(r"(?i)dire[cç][aã]o\s*:\s*(BUY|SELL)", text)
    direction = dir_match.group(1).upper() if dir_match else None

    if not symbol or not timeframe or direction not in ("BUY", "SELL"):
        return None
    if timeframe not in (1, 5):
        return None

    expiration = f"0{timeframe}:00" if timeframe < 10 else f"{timeframe}:00"

    return {
        "type": "entry",
        "symbol": symbol,
        "timeframe_minutes": timeframe,
        "expiration": expiration,  # compat: alguns consumidores podem esperar
        "direction": direction,
    }

def _parse_result(text: str):
    """
    Formato esperado:
    ✅ RESULTADO: WIN
    ❌ RESULTADO: LOSS
    """
    m = re.search(r"(?i)\bRESULTADO\s*:\s*(WIN|LOSS)\b", text)
    if not m:
        return None
    return {"type": "result", "result": m.group(1).upper()}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        print("⚠️ Mensagem ignorada: não é texto ou está vazia.")
        return

    text = update.message.text.strip()

    print("\n📥 Mensagem recebida:")
    print(f"🧑‍💬 De: {update.message.from_user.full_name} (ID: {update.message.from_user.id})")
    print(f"📝 Texto: {text}")

    # Entrada imediata
    entry_payload = _parse_entry(text)
    if entry_payload:
        print("📤 Publicando ENTRADA:", entry_payload)
        await send_to_queue(entry_payload)
        return

    # Resultado
    result_payload = _parse_result(text)
    if result_payload:
        print("📤 Publicando RESULTADO:", result_payload)
        await send_to_queue(result_payload)
        return

    print("ℹ️ Mensagem ignorada: formato não reconhecido pelo parser atual.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    # Grupos, supergrupos e canais (onde sinais normalmente chegam)
    app.add_handler(
        MessageHandler(
            filters.TEXT & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP | filters.ChatType.CHANNELS),
            handle_message
        )
    )
    print("🤖 Bot iniciado e aguardando mensagens...")
    app.run_polling()

if __name__ == "__main__":
    main()
