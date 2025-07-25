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

    exchange = await channel.declare_exchange("avalon_signals", aio_pika.ExchangeType.FANOUT)

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

    # 🔍 Debug: mensagem recebida
    print("\n📥 Mensagem recebida:")
    print(f"🧑‍💬 De: {update.message.from_user.full_name} (ID: {update.message.from_user.id})")
    print(f"📝 Texto: {text}")

    # 🎯 Caso 1: Sinal de entrada
    if "✅ ENTRADA CONFIRMADA ✅" in text:
        ativo_match = re.search(r"Ativo:\s*(.+)", text)
        expiracao_match = re.search(r"Expiração:\s*(.+)", text)
        entrada_match = re.search(r"Entrada:\s*(\d{2}:\d{2})", text)
        direcao_match = re.search(r"Direção:\s*Entrada\s+em\s+(\w+)", text)
        gales_match = re.findall(r"\dº GALE: TERMINA EM: (\d{2}:\d{2})", text)

        ativo = ativo_match.group(1).strip() if ativo_match else None

        if ativo and '/' in ativo:
            partes = ativo.split('/')
            ativo = ''.join(partes)

        expiracao = expiracao_match.group(1).strip() if expiracao_match else None
        entrada = entrada_match.group(1).strip() if entrada_match else None
        direcao = direcao_match.group(1).strip() if direcao_match else None
        gale1 = gales_match[0] if len(gales_match) > 0 else None
        gale2 = gales_match[1] if len(gales_match) > 1 else None

        # Debug dos valores extraídos
        print("🔎 Match ativo:", ativo)
        print("🔎 Match expiracao:", expiracao)
        print("🔎 Match entrada:", entrada)
        print("🔎 Match direcao:", direcao)
        print("🔎 Match gale1:", gale1)
        print("🔎 Match gale2:", gale2)

        if expiracao == "M1":
            expiracao = "01:00"
        elif expiracao == "M5":
            expiracao = "05:00"

        if direcao and direcao.lower() == "call":
            direcao = "BUY"
        elif direcao and direcao.lower() == "put":
            direcao = "SELL"

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

    # 🎯 Caso 2: Resultado (WIN ou LOSS)
    elif text.upper() in ["WIN", "LOSS"]:
        resultado = text.upper()
        print(f"🏁 Resultado detectado: {resultado}")
        result_payload = {
            "type": "result",
            "result": resultado
        }
        print("📤 Publicando resultado:", result_payload)
        await send_to_queue(result_payload)

    # 🎯 Caso 3: Detecção de gale
    elif text.startswith("🔄 Fazer gale"):
        print("♻️ Mensagem de gale detectada")
        gale_match = re.search(r"Fazer gale\s+(\d+)", text)
        if gale_match:
            gale_count = int(gale_match.group(1))
            print(f"🔁 GALE identificado: {gale_count}")
            gale_payload = {
                "type": "gale_trigger",
                "gale": gale_count
            }
            print("📤 Publicando trigger de gale:", gale_payload)
            await send_to_queue(gale_payload)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, handle_message))
    print("🤖 Bot iniciado e aguardando mensagens...")
    app.run_polling()

if __name__ == "__main__":
    main()
