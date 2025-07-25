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
    get_user_brokerages
)
from datetime import datetime
import pytz

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
USER_ID = os.getenv("USER_ID")
BROKERAGE_ID = os.getenv("BROKERAGE_ID")
host = os.getenv("RABBITMQ_HOST")
user = os.getenv("RABBITMQ_USER")
password = os.getenv("RABBITMQ_PASS")
RABBITMQ_URL = f"amqp://{user}:{password}@{host}:5672/"

resultado_global = None
sinal_ativo = None
proxima_gale = 1

print("🔗 RabbitMQ URL:", RABBITMQ_URL)

def inverter_symbol(symbol: str) -> str:
    if ".OTC" in symbol:
        base, _ = symbol.split(".OTC")
        if len(base) == 6:
            return base[3:] + base[:3] + ".OTC"
    elif len(symbol) == 6:
        return symbol[3:] + symbol[:3]
    return symbol

async def consultar_balance(account_type: str):
    url = "http://localhost:3002/api/account/balance"
    headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                for wallet in data.get("Wallets", []):
                    if wallet["type"] == account_type:
                        return wallet["amount"]
            return None

async def realizar_compra(isDemo: bool, close_type: str, direction: str, symbol: str, amount: float):
    url_buy = 'http://localhost:3002/api/trade/digital/buy'
    user_brokerages = await get_user_brokerages(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    EMAIL = user_brokerages['brokerage_username']
    PASSWORD = user_brokerages['brokerage_password']

    period_seconds = 0
    if close_type:
        parts = close_type.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = int(parts[1])
            period_seconds = minutes * 60 + seconds

    api_direction = "CALL" if direction == "BUY" else "PUT"
    account_type = "demo" if isDemo else "real"

    balance_antes = await consultar_balance(account_type)

    payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "assetName": symbol,
        "operationValue": float(amount),
        "direction": api_direction,
        "account_type": account_type,
        "period": period_seconds
    }

    headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url_buy, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    order_id = str(data.get("id", ""))
                    await asyncio.sleep(2)
                    balance_depois = await consultar_balance(account_type)
                    pnl = 0
                    if balance_antes is not None and balance_depois is not None:
                        pnl = round(balance_depois - balance_antes, 2)
                    else:
                        pnl = 0

                    return {
                        "id": order_id,
                        "result": data.get("status", ""),
                        "openPrice": data.get("open_price", 0),
                        "pnl": pnl
                    }
                else:
                    print(f"❌ Erro ao enviar ordem: status {response.status}")
                    return {}
        except Exception as e:
            print(f"⚠️ Erro de requisição ao enviar ordem: {e}")
            return {}

async def tentar_ordem_com_inversao(isDemo, close_type, direction, symbol, amount, etapa):
    if amount > 1000:
        amount = 1000

    order = await realizar_compra(isDemo, close_type, direction, symbol, amount)
    if not order.get("id"):
        symbol_invertido = inverter_symbol(symbol)
        print(f"🔁 Tentando com símbolo invertido: {symbol_invertido}")
        order = await realizar_compra(isDemo, close_type, direction, symbol_invertido, amount)
        if order.get("id"):
            symbol = symbol_invertido

    if not order.get("id"):
        print("❌ Falha ao enviar ordem mesmo após inversão.")
        return None

    await create_trade_order_info(user_id=USER_ID, order_id=order["id"], symbol=symbol, order_type=direction,
                                  quantity=amount, price=order.get("openPrice"), status=order.get("result"),
                                  brokerage_id=BROKERAGE_ID)
    return order

async def aguardar_resultado(timeout=60):
    global resultado_global
    for _ in range(timeout):
        if resultado_global in ["WIN", "LOSS"]:
            result = resultado_global
            resultado_global = None
            return result
        await asyncio.sleep(1)
    return None

async def executar_gale_com_timeout(n_gale, isDemo, close_type, direction, symbol, amount):
    print(f"🚨 Executando Gale {n_gale}")
    valor = amount * (2 ** n_gale)
    etapa = f"Gale {n_gale}"
    order = await tentar_ordem_com_inversao(isDemo, close_type, direction, symbol, valor, etapa)
    result = await aguardar_resultado(70)

    if result == "WIN":
        await update_win_value(user_id=USER_ID, win_value=order['pnl'], brokerage_id=BROKERAGE_ID)
        await update_trade_order_info(order_id=order['id'], user_id=USER_ID, status=f"WON NA {etapa.upper()}", pnl=order['pnl'])
    else:
        await update_loss_value(user_id=USER_ID, loss_value=valor, brokerage_id=BROKERAGE_ID)
        await update_trade_order_info(order_id=order['id'], user_id=USER_ID, status="LOST", pnl=order['pnl'])
    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)

async def aguardar_horario(horario: str, etapa: str):
    print(f"⏳ Aguardando horário: {horario} para {etapa}")
    tz_brasilia = pytz.timezone('America/Sao_Paulo')
    target_time = datetime.strptime(horario, "%H:%M").time()
    while True:
        agora = datetime.now(tz_brasilia).time()
        if agora >= target_time:
            print("🚀 Horário atingido, prosseguindo...")
            return
        await asyncio.sleep(5)

async def aguardar_e_executar_entradas(data):
    global sinal_ativo, proxima_gale
    sinal_ativo = data
    proxima_gale = 1

    entrada = data["entry_time"]
    gale1 = data["gale1"]
    gale2 = data["gale2"]
    close_type = data["expiration"]
    direction = data["direction"]
    symbol = data["symbol"]

    bot_options = await get_bot_options(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    amount = bot_options['entry_price']
    isDemo = bot_options['is_demo']

    await aguardar_horario(entrada, "Entrada Principal")
    order = await tentar_ordem_com_inversao(isDemo, close_type, direction, symbol, amount, "Entrada Principal")

    result = await aguardar_resultado()
    if result == "WIN":
        await update_win_value(user_id=USER_ID, win_value=order['pnl'], brokerage_id=BROKERAGE_ID)
        await update_trade_order_info(order_id=order['id'], user_id=USER_ID, status="WON", pnl=order['pnl'])
        await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    else:
        if gale1:
            await aguardar_horario(gale1, "Gale 1")
            await executar_gale_com_timeout(1, isDemo, close_type, direction, symbol, amount)
        if gale2:
            await aguardar_horario(gale2, "Gale 2")
            await executar_gale_com_timeout(2, isDemo, close_type, direction, symbol, amount)

async def main():
    global resultado_global, sinal_ativo

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange("avalon_signals", aio_pika.ExchangeType.FANOUT)
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange)

    print("✅ Aguardando sinais...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                data = json.loads(message.body.decode())
                tipo = data.get("type")

                if tipo == "result":
                    resultado_global = data.get("result")
                    print(f"📊 Resultado recebido: {resultado_global}")

                elif tipo == "entry":
                    print("📥 Sinal recebido:", data)
                    await aguardar_e_executar_entradas(data)

                elif tipo == "gale_trigger":
                    gale = data.get("gale")
                    print(f"🔔 Trigger de GALE {gale} recebido (mas usando fallback de timeout)")
                    # Ignorado, pois fallback por timeout é padrão agora

if __name__ == "__main__":
    asyncio.run(main())
