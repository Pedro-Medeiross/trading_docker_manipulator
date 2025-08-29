import os
import re
import json
import asyncio
import aio_pika
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# Carrega variáveis de ambiente
load_dotenv()
TOKEN = os.getenv("TOKEN_TELEGRAM")
RABBITMQ_URL = os.getenv("RABBITMQ_URL")

# =========================
# Publicação no RabbitMQ
# =========================
async def send_to_queue(data: dict):
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

# =========================
# Funções de parsing
# =========================
def _normalize_symbol(sym: str | None) -> str | None:
    if not sym:
        return None
    return sym.strip().upper().replace("/", "")  # remove "/" mas mantém "-"

def _parse_entry(text: str) -> dict | None:
    """
    Exemplo esperado:
    🚀 NOVA ENTRADA
    • Par: EURUSD  ou EURUSD-OTC
    • Timeframe: 1 | 5 | M1 | M5 | 1m | 5m
    • Direção: BUY | SELL
    """
    if not re.search(r"(?i)\bNOVA\s+ENTRADA\b", text):
        return None

    par_match = re.search(r"(?i)par\s*:\s*([A-Z/\-]{6,20})", text)
    symbol = _normalize_symbol(par_match.group(1)) if par_match else None

    tf_match = re.search(
        r"(?i)(?:time\s*frame|timeframe)\s*:\s*(M?\s*([15])|([15])\s*m?)",
        text
    )
    timeframe = int(tf_match.group(2) or tf_match.group(3)) if tf_match else None

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
        "expiration": expiration,
        "direction": direction,
    }

def _parse_result(text: str) -> dict | None:
    """
    Exemplo esperado:
    ✅ RESULTADO: WIN
    ❌ RESULTADO: LOSS
    """
    m = re.search(r"(?i)\bRESULTADO\s*:\s*(WIN|LOSS)\b", text)
    if not m:
        return None
    return {"type": "result", "result": m.group(1).upper()}

# =========================
# Handler das mensagens
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    print("\n📥 Mensagem recebida:")
    print(f"📝 Texto: {text}")

    entry_payload = _parse_entry(text)
    if entry_payload:
        print("📤 Publicando ENTRADA:", entry_payload)
        await send_to_queue(entry_payload)
        return

    result_payload = _parse_result(text)
    if result_payload:
        print("📤 Publicando RESULTADO:", result_payload)
        await send_to_queue(result_payload)
        return

    print("ℹ️ Ignorado: formato não reconhecido.")

# =========================
# Main
# =========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(
        MessageHandler(
            filters.TEXT & (filters.ChatType.GROUPS | filters.ChatType.CHANNEL),
            handle_message
        )
    )
    print("🤖 Bot Polarium Publisher iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
