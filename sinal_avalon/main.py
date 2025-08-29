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


# === Publicação no RabbitMQ ===
async def send_to_queue(data: dict):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    exchange = await channel.declare_exchange(
        "avalon_signals",
        aio_pika.ExchangeType.FANOUT
    )

    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(data).encode(),
            delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT
        ),
        routing_key=""
    )

    await connection.close()


# === Parsers ===
def _normalize_symbol(sym: str | None) -> str | None:
    if not sym:
        return None
    sym = sym.strip().upper()
    # remove "/" mas mantém hifens (ex.: EURUSD-OTC)
    sym = sym.replace("/", "")
    return sym


def _parse_entry(text: str):
    """
    Formato esperado:
    🚀 NOVA ENTRADA
    • Par: EURUSD
      ou: EURUSD-OTC
    • Timeframe: 1
    • Direção: BUY
    """
    if not re.search(r"\bNOVA\s+ENTRADA\b", text, re.IGNORECASE):
        return None

    # Par
    par_match = re.search(r"(?i)par\s*:\s*([A-Z/\-]{6,20})", text)
    symbol = _normalize_symbol(par_match.group(1)) if par_match else None

    # Timeframe
    tf_match = re.search(r"(?i)(?:time\s*frame|timeframe)\s*:\s*(\d+)", text)
    timeframe = int(tf_match.group(1)) if tf_match else None

    # Direção
    dir_match = re.search(r"(?i)dire[cç][aã]o\s*:\s*(BUY|SELL)", text)
    direction = dir_match.group(1).upper() if dir_match else None

    if not symbol or not timeframe or direction not in ("BUY", "SELL"):
        return None

    expiration = f"0{timeframe}:00" if timeframe < 10 else f"{timeframe}:00"

    return {
        "type": "entry",
        "symbol": symbol,                 # ex.: EURUSD-OTC
        "timeframe_minutes": timeframe,   # 1, 5, etc.
        "expiration": expiration,
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
    return {
        "type": "result",
        "result": m.group(1).upper()
    }


# === Handler de mensagens do Telegram ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.message.from_user

    print("\n📥 Mensagem recebida:")
    print(f"🧑‍💬 {user.full_name if user else 'desconhecido'} "
          f"(ID: {user.id if user else 'n/a'})")
    print(f"📝 {text}")

    # Entrada
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

    print("ℹ️ Mensagem ignorada: formato não reconhecido.")


# === Main ===
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & (filters.ChatType.GROUPS | filters.ChatType.CHANNEL),
            handle_message
        )
    )

    # Caso queira também no privado:
    # app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_message))

    print("🤖 Bot Avalon iniciado e aguardando mensagens...")
    app.run_polling()


if __name__ == "__main__":
    main()
