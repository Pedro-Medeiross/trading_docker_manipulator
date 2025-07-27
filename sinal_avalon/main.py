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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        print("⚠️ Mensagem ignorada: não é texto ou está vazia.")
        return

    text = update.message.text.strip()

    print("\n📥 Mensagem recebida:")
    print(f"🧑‍💬 De: {update.message.from_user.full_name} (ID: {update.message.from_user.id})")
    print(f"📝 Texto: {text}")

    # 🎯 Caso 1: Entrada confirmada
    if "✅ENTRADA CONFIRMADA✅" in text:
        ativo_match = re.search(r"Ativo:\s*(.+)", text)
        expiracao_match = re.search(r"Expiração:\s*M(\d+)", text)
        direcao_match = re.search(r"Direção:\s*(.+)", text)
        entrada_match = re.search(r"Entrada:\s*(\d{2}:\d{2})", text)
        gales_match = re.findall(r"(\d)º GALE: TERMINA EM: (\d{2}:\d{2})", text)

        ativo = ativo_match.group(1).strip() if ativo_match else None
        if ativo and '/' in ativo:
            ativo = ''.join(ativo.split('/'))

        expiracao = f"0{expiracao_match.group(1)}:00" if expiracao_match else None
        entrada = entrada_match.group(1).strip() if entrada_match else None

        direcao_raw = direcao_match.group(1).strip().lower() if direcao_match else None
        if "compra" in direcao_raw:
            direcao = "BUY"
        elif "venda" in direcao_raw:
            direcao = "SELL"
        else:
            direcao = None

        gale1 = gale2 = None
        for g in gales_match:
            if g[0] == '1':
                gale1 = g[1]
            elif g[0] == '2':
                gale2 = g[1]

        signal = {
            "type": "entry",
            "symbol": ativo,
            "expiration": expiracao,
            "entry_time": entrada,
            "direction": direcao,
            "gale1": gale1,
            "gale2": gale2
        }

        print("📤 Publicando sinal de entrada:", signal)
        await send_to_queue(signal)

    # 🎯 Caso 2: Resultado WIN
    elif "GAIN" in text.upper() and "MARTINGALE" not in text.upper():
        result_payload = {
            "type": "result",
            "result": "WIN"
        }
        print("📤 Publicando resultado WIN:", result_payload)
        await send_to_queue(result_payload)

    # 🎯 Caso 3: Resultado LOSS
    elif "LOSS" in text.upper():
        result_payload = {
            "type": "result",
            "result": "LOSS"
        }
        print("📤 Publicando resultado LOSS:", result_payload)
        await send_to_queue(result_payload)

    # 🎯 Ignorar GAIN Martingale
    elif re.search(r"GAIN Martingale \d", text, re.IGNORECASE):
        print("⚠️ Ignorado: Resultado GAIN com Martingale não será publicado.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, handle_message))
    print("🤖 Bot iniciado e aguardando mensagens...")
    app.run_polling()

if __name__ == "__main__":
    main()
