import os
import json
import asyncio
import aio_pika
from dotenv import load_dotenv
from api import (
    get_bot_options,
    update_win_value,
    update_loss_value,
    update_trade_order_info,
    verify_stop_values,
    create_trade_order_info
)
from datetime import datetime
import pytz
import requests

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
USER_ID = os.getenv("USER_ID")
BROKERAGE_ID = os.getenv("BROKERAGE_ID")
host = os.getenv("RABBITMQ_HOST")
user = os.getenv("RABBITMQ_USER")
password = os.getenv("RABBITMQ_PASS")
RABBITMQ_URL = f"amqp://{user}:{password}@{host}:5672/"

print("🔗 RabbitMQ URL:", RABBITMQ_URL)

def realizar_compra(isDemo: bool, close_type: str, direction: str, symbol: str, amount: float):
    url_buy = 'https://broker-api.mybroker.dev/token/trades/open'
    payload = {
        "isDemo": isDemo,
        "closeType": close_type,
        "direction": direction,
        "symbol": symbol,
        "amount": amount
    }
    headers = {"content-type": "application/json", "api-token": API_TOKEN}
    response = requests.post(url_buy, json=payload, headers=headers)
    data = response.json()
    print("📤 Ordem enviada:", data)
    return data

async def executar_ordem_e_verificar(isDemo, close_type, direction, symbol, amount, etapa):
    order = realizar_compra(isDemo, close_type, direction, symbol, amount)
    order_id = order.get("id")
    order_price = order.get("openPrice")
    order_status = order.get("result")

    if not order_id:
        print("❌ Falha ao enviar ordem.")
        return None

    await create_trade_order_info(USER_ID, order_id, symbol, direction, amount, order_price, order_status, BROKERAGE_ID)

    url_status = f"https://broker-api.mybroker.dev/token/trades/{order_id}"
    headers = {"api-token": API_TOKEN}

    print(f"🔍 Verificando resultado da ordem {order_id} para {etapa}...")
    while True:
        await asyncio.sleep(5)
        try:
            response = requests.get(url_status, headers=headers)
            data = response.json()
            result = data.get("result")
            print(f"📊 Status atual: {result}")
            if result in ["WON", "LOST", "DRAW"]:
                return data
        except Exception as e:
            print(f"⚠️ Erro ao verificar status: {e}")

async def aguardar_horario(horario: str, etapa: str):
    print(f"⏳ Aguardando horário: {horario} para {etapa}")
    tz_brasilia = pytz.timezone('America/Sao_Paulo')
    target_time = datetime.strptime(horario, "%H:%M").time()
    while True:
        agora = datetime.now(tz_brasilia).time()
        print(f"🕒 Horário atual: {agora.strftime('%H:%M:%S')} para {etapa}")
        if agora >= target_time:
            print("🚀 Horário atingido, prosseguindo...")
            return
        await asyncio.sleep(5)

async def aguardar_e_executar_entradas(data):
    entrada = data["entry_time"]
    gale1 = data["gale1"]
    gale2 = data["gale2"]
    close_type = data["expiration"]
    direction = data["direction"]
    symbol = data["symbol"]

    bot_options = await get_bot_options(USER_ID)
    amount = bot_options['entry_price']
    isDemo = bot_options['is_demo']
    gale_one = bot_options['gale_one']
    gale_two = bot_options['gale_two']

    await aguardar_horario(entrada, "Entrada Principal")
    order = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, amount, "Entrada Principal")

    if not order:
        print("⚠️ Falha na execução da entrada principal.")
        return

    result = order.get("result")
    pnl = order.get("pnl")

    if result == "WON":
        await update_win_value(USER_ID, pnl)
        await update_trade_order_info(order["id"], USER_ID, "WON")
        await verify_stop_values(USER_ID)
        return

    await update_loss_value(USER_ID, amount)
    await update_trade_order_info(order["id"], USER_ID, "LOST")
    await verify_stop_values(USER_ID)

    if (result in ["LOST", "DRAW"]) and gale1 and gale_one:
        await aguardar_horario(gale1, "Gale 1")
        gale1_valor = amount * 2
        order_g1 = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, gale1_valor, "Gale 1")

        if order_g1 and order_g1.get("result") == "WON":
            await update_win_value(USER_ID, order_g1["pnl"])
            await update_trade_order_info(order_g1["id"], USER_ID, "WON NA GALE 1")
            await verify_stop_values(USER_ID)
            return

        await update_loss_value(USER_ID, gale1_valor)
        await update_trade_order_info(order_g1["id"], USER_ID, "LOST")
        await verify_stop_values(USER_ID)

        if (order_g1 and order_g1.get("result") in ["LOST", "DRAW"]) and gale2 and gale_two:
            await aguardar_horario(gale2, "Gale 2")
            gale2_valor = amount * 4
            order_g2 = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, gale2_valor, "Gale 2")

            if order_g2 and order_g2.get("result") == "WON":
                await update_win_value(USER_ID, order_g2["pnl"])
                await update_trade_order_info(order_g2["id"], USER_ID, "WON NA GALE 2")
            else:
                await update_loss_value(USER_ID, gale2_valor)
                await update_trade_order_info(order_g2["id"], USER_ID, "LOST")
            await verify_stop_values(USER_ID)

# Consumidor do RabbitMQ com exchange fanout
async def main():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    # Declara o exchange do tipo fanout
    exchange = await channel.declare_exchange("bot_signals", aio_pika.ExchangeType.FANOUT)

    # Declara uma fila temporária exclusiva para este consumidor
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange)

    print("✅ Aguardando sinais...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                data = json.loads(message.body.decode())
                print("📥 Sinal recebido:", data)
                await aguardar_e_executar_entradas(data)

if __name__ == "__main__":
    asyncio.run(main())
