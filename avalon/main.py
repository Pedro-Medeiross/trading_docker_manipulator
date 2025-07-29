import os
import json
import asyncio
import aio_pika
import aiohttp
from dotenv import load_dotenv
from api import (
    get_bot_options,
    update_win_value,
    update_loss_value,
    update_trade_order_info,
    verify_stop_values,
    create_trade_order_info,
)
from datetime import datetime
import pytz
import uuid

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
USER_ID = os.getenv("USER_ID")
BROKERAGE_ID = os.getenv("BROKERAGE_ID")
host = os.getenv("RABBITMQ_HOST")
user = os.getenv("RABBITMQ_USER")
password = os.getenv("RABBITMQ_PASS")
RABBITMQ_URL = f"amqp://{user}:{password}@{host}:5672/"
BROKERAGE_USERNAME = os.getenv("BROKERAGE_USERNAME")
BROKERAGE_PASSWORD = os.getenv("BROKERAGE_PASSWORD")

# Variáveis globais
resultado_global = None
proxima_etapa = asyncio.Event()
etapa_atual = None


async def consultar_balance(account_type: str):
    url = "http://avalon_api:3001/api/account/balance"
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                for wallet in data.get("Wallets", []):
                    if wallet["type"] == account_type:
                        return wallet["amount"]
    return None


async def realizar_compra(isDemo, close_type, direction, symbol, amount, trade_id):
    url = 'http://avalon_api:3001/api/trade/digital/buy'
    account_type = "demo" if isDemo else "real"
    api_direction = "CALL" if direction == "BUY" else "PUT"

    minutes, seconds = map(int, close_type.split(":"))
    period_seconds = minutes * 60 + seconds

    payload = {
        "email": BROKERAGE_USERNAME,
        "password": BROKERAGE_PASSWORD,
        "assetName": symbol,
        "operationValue": float(amount),
        "direction": api_direction,
        "account_type": account_type,
        "period": period_seconds
    }

    headers = {"Content-Type": "application/json"}
    balance_before = await consultar_balance(account_type)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                if response.status == 201:
                    await asyncio.sleep(2)
                    balance_after = await consultar_balance(account_type)
                    pnl = round(balance_after - balance_before, 2) if balance_before and balance_after else 0
                    return {
                        "id": trade_id,
                        "result": data.get("status", ""),
                        "openPrice": data.get("open_price", 0),
                        "pnl": pnl
                    }
        except Exception as e:
            print(f"❌ Erro na requisição da ordem: {e}")
    return {}


async def tentar_ordem(isDemo, close_type, direction, symbol, amount, etapa):
    trade_id = str(uuid.uuid4())
    await create_trade_order_info(user_id=USER_ID, order_id=trade_id, symbol=symbol, order_type=direction,
                                  quantity=amount, price=0, status="PENDING", brokerage_id=BROKERAGE_ID)
    return await realizar_compra(isDemo, close_type, direction, symbol, amount, trade_id)


async def aguardar_horario(horario, etapa):
    tz = pytz.timezone("America/Sao_Paulo")
    target = datetime.strptime(horario, "%H:%M").time()
    while True:
        now = datetime.now(tz).time()
        if now >= target:
            return
        await asyncio.sleep(5)


async def aguardar_resultado_por_evento():
    global resultado_global, proxima_etapa
    await proxima_etapa.wait()
    proxima_etapa.clear()
    res = resultado_global
    resultado_global = None
    return res


async def aguardar_e_executar_entradas(data):
    global resultado_global, etapa_atual

    symbol = data["symbol"]
    direction = data["direction"]
    close_type = data["expiration"]
    entrada = data["entry_time"]
    gale1 = data["gale1"]
    gale2 = data["gale2"]

    bot_options = await get_bot_options(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    amount = bot_options['entry_price']
    isDemo = bot_options['is_demo']

    # ENTRADA PRINCIPAL
    etapa_atual = "entry"
    await aguardar_horario(entrada, "Entrada Principal")
    ordem_principal = await tentar_ordem(isDemo, close_type, direction, symbol, amount, "Entrada Principal")
    if not ordem_principal:
        return

    res = await aguardar_resultado_por_evento()
    if res == "WIN":
        await update_win_value(USER_ID, ordem_principal["pnl"], BROKERAGE_ID)
        await update_trade_order_info(ordem_principal["id"], USER_ID, "WON", ordem_principal["pnl"])
        await verify_stop_values(USER_ID, BROKERAGE_ID)
        return
    else:
        await update_loss_value(USER_ID, amount, BROKERAGE_ID)
        await update_trade_order_info(ordem_principal["id"], USER_ID, "LOST", ordem_principal["pnl"])

    # GALE 1
    if gale1:
        etapa_atual = "gale1"
        await aguardar_horario(gale1, "Gale 1")
        ordem_gale1 = await tentar_ordem(isDemo, close_type, direction, symbol, amount * 2, "Gale 1")
        if not ordem_gale1:
            return

        res = await aguardar_resultado_por_evento()
        if res == "WIN":
            await update_win_value(USER_ID, ordem_gale1["pnl"], BROKERAGE_ID)
            await update_trade_order_info(ordem_gale1["id"], USER_ID, "WON NA GALE 1", ordem_gale1["pnl"])
            await verify_stop_values(USER_ID, BROKERAGE_ID)
            return
        else:
            await update_loss_value(USER_ID, amount * 2, BROKERAGE_ID)
            await update_trade_order_info(ordem_gale1["id"], USER_ID, "LOST", ordem_gale1["pnl"])

    # GALE 2
    if gale2:
        etapa_atual = "gale2"
        await aguardar_horario(gale2, "Gale 2")
        ordem_gale2 = await tentar_ordem(isDemo, close_type, direction, symbol, amount * 4, "Gale 2")
        if not ordem_gale2:
            return

        res = await aguardar_resultado_por_evento()
        if res == "WIN":
            await update_win_value(USER_ID, ordem_gale2["pnl"], BROKERAGE_ID)
            await update_trade_order_info(ordem_gale2["id"], USER_ID, "WON NA GALE 2", ordem_gale2["pnl"])
        else:
            await update_loss_value(USER_ID, amount * 4, BROKERAGE_ID)
            await update_trade_order_info(ordem_gale2["id"], USER_ID, "LOST", ordem_gale2["pnl"])
        await verify_stop_values(USER_ID, BROKERAGE_ID)


async def main():
    global resultado_global, proxima_etapa, etapa_atual

    print("🔌 Conectando ao RabbitMQ...")
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange("avalon_signals", aio_pika.ExchangeType.FANOUT)
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange)
    print("✅ Conectado e escutando mensagens...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    data = json.loads(message.body.decode())
                    tipo = data.get("type")

                    if tipo == "result":
                        resultado_global = data.get("result")
                        proxima_etapa.set()

                    elif tipo == "gale":
                        step = data.get("step")
                        if (step == 1 and etapa_atual == "gale1") or (step == 2 and etapa_atual == "gale2"):
                            # apenas permitir avanço se for a etapa correta
                            continue

                    elif tipo == "entry":
                        asyncio.create_task(aguardar_e_executar_entradas(data))

                except Exception as e:
                    print(f"Erro ao processar mensagem: {e}")


if __name__ == "__main__":
    asyncio.run(main())
