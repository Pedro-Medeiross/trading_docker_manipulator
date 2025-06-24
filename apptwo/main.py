# publisher.py
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

    # Cria (ou usa) um exchange do tipo fanout
    exchange = await channel.declare_exchange("bot_signals", aio_pika.ExchangeType.FANOUT)

    # Publica a mensagem no exchange (fanout ignora routing_key)
    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(data).encode(),
            delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT  # não persistente
        ),
        routing_key=""
    )

    await connection.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and "✅ ENTRADA CONFIRMADA ✅" in update.message.text:
        text = update.message.text

        ativo_match = re.search(r"Ativo:\s*(.+)", text)
        expiracao_match = re.search(r"Expiração:\s*(.+)", text)
        entrada_match = re.search(r"Entrada:\s*(\d{2}:\d{2})", text)
        direcao_match = re.search(r"Direção:\s*[\S]+\s+([A-Z]+)", text)
        gales_match = re.findall(r"\dº GALE: TERMINA EM: (\d{2}:\d{2})", text)

        ativo = ativo_match.group(1).strip() if ativo_match else None
        expiracao = expiracao_match.group(1).strip() if expiracao_match else None
        entrada = entrada_match.group(1).strip() if entrada_match else None
        direcao = direcao_match.group(1).strip() if direcao_match else None
        gale1 = gales_match[0] if len(gales_match) > 0 else None
        gale2 = gales_match[1] if len(gales_match) > 1 else None

        if expiracao == "M1":
            expiracao = "01:00"
        elif expiracao == "M5":
            expiracao = "05:00"

        if direcao == "COMPRA":
            direcao = "BUY"
        elif direcao == "VENDA":
            direcao = "SELL"

        signal = {
            "symbol": ativo,
            "expiration": expiracao,
            "entry_time": entrada,
            "direction": direcao,
            "gale1": gale1,
            "gale2": gale2
        }

        print("📤 Publicando sinal:", signal)
        await send_to_queue(signal)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
