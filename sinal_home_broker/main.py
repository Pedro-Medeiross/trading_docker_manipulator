# publisher_home_broker.py
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
    exchange = await channel.declare_exchange("home_broker_signals", aio_pika.ExchangeType.FANOUT)

    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(data).encode(),
            delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT
        ),
        routing_key=""
    )
    await connection.close()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text

    # -----------------------------
    # 1) FORMATO ANTIGO: ENTRADA CONFIRMADA
    # -----------------------------
    if "✅ ENTRADA CONFIRMADA ✅" in text:
        ativo_match = re.search(r"Ativo:\s*(.+)", text)
        expiracao_match = re.search(r"Expiração:\s*(.+)", text)
        entrada_match = re.search(r"Entrada:\s*(\d{2}:\d{2})", text)
        direcao_match = re.search(r"Direção:\s*[\S]+\s+([A-Z]+)", text)

        ativo = ativo_match.group(1).strip() if ativo_match else None
        if ativo and '/' in ativo:
            ativo = ''.join(ativo.split('/'))

        expiracao = expiracao_match.group(1).strip() if expiracao_match else None
        entrada = entrada_match.group(1).strip() if entrada_match else None
        direcao = direcao_match.group(1).strip() if direcao_match else None

        # Converte Expiração para minutos
        if expiracao == "M1":
            timeframe = 1
        elif expiracao == "M5":
            timeframe = 5
        else:
            timeframe = 1  # default

        if direcao == "COMPRA":
            direcao = "BUY"
        elif direcao == "VENDA":
            direcao = "SELL"

        signal = {
            "type": "entry",
            "symbol": ativo,
            "timeframe_minutes": timeframe,
            "direction": direcao,
            "entry_time": entrada  # pode ser usado no consumer home_broker
        }

        print("📤 Publicando sinal (confirmado):", signal)
        await send_to_queue(signal)

    # -----------------------------
    # 2) NOVO FORMATO: 🚀 NOVA ENTRADA
    # -----------------------------
    elif "🚀 NOVA ENTRADA" in text:
        par_match = re.search(r"Par:\s*(.+)", text)
        timeframe_match = re.search(r"Timeframe:\s*(\d+)", text)
        direcao_match = re.search(r"Direção:\s*([A-Z]+)", text)

        ativo = par_match.group(1).strip() if par_match else None
        if ativo and '/' in ativo:
            ativo = ''.join(ativo.split('/'))

        timeframe = int(timeframe_match.group(1).strip()) if timeframe_match else 1
        direcao = direcao_match.group(1).strip() if direcao_match else None

        if direcao == "COMPRA":
            direcao = "BUY"
        elif direcao == "VENDA":
            direcao = "SELL"

        signal = {
            "type": "entry",
            "symbol": ativo,
            "timeframe_minutes": timeframe,
            "direction": direcao
        }

        print("📤 Publicando sinal (nova entrada):", signal)
        await send_to_queue(signal)

    # -----------------------------
    # 3) RESULTADO (WIN / LOSS)
    # -----------------------------
    elif "RESULTADO" in text:
        result_match = re.search(r"RESULTADO:\s*(WIN|LOSS)", text)
        if result_match:
            resultado = result_match.group(1).strip()

            signal = {
                "type": "result",
                "result": resultado
            }

            print("📤 Publicando resultado:", signal)
            await send_to_queue(signal)


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
