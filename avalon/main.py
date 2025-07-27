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

resultado_global = None
sinal_ativo = None
proxima_gale = 1

print("🔗 RabbitMQ URL:", RABBITMQ_URL)

def inverter_symbol(symbol: str) -> str:
    return symbol

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

async def realizar_compra(isDemo: bool, close_type: str, direction: str, symbol: str, amount: float, trade_id: str):
    url_buy = 'http://avalon_api:3001/api/trade/digital/buy'

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
        "email": BROKERAGE_USERNAME,
        "password": BROKERAGE_PASSWORD,
        "assetName": symbol,
        "operationValue": float(amount),
        "direction": api_direction,
        "account_type": account_type,
        "period": period_seconds
    }

    headers = {"Content-Type": "application/json"}

    print(f"📤 Enviando ordem para {symbol} ({api_direction}) | Valor: {amount} | Periodo: {close_type}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url_buy, json=payload, headers=headers) as response:
                data = await response.json()
                if response.status == 201:
                    await asyncio.sleep(2)
                    balance_depois = await consultar_balance(account_type)
                    pnl = 0
                    if balance_antes is not None and balance_depois is not None:
                        pnl = round(balance_depois - balance_antes, 2)
                    else:
                        pnl = 0

                    print(f"✅ Ordem enviada: ID {trade_id}, PnL: {pnl}")
                    return {
                        "id": trade_id,
                        "result": data.get("status", ""),
                        "openPrice": data.get("open_price", 0),
                        "pnl": pnl
                    }
                else:
                    print(f"❌ Erro ao enviar ordem: status {response.status}")
                    print("Resposta:", data)
                    return {}
        except Exception as e:
            print(f"⚠️ Erro de requisição ao enviar ordem: {e}")
            return {}

async def tentar_ordem(isDemo, close_type, direction, symbol, amount, etapa):
    if amount > 1000:
        amount = 1000

    trade_id = str(uuid.uuid4())
    await create_trade_order_info(user_id=USER_ID, order_id=trade_id, symbol=symbol, order_type=direction,
                                  quantity=amount, price=0, status="PENDING", brokerage_id=BROKERAGE_ID)

    order = await realizar_compra(isDemo, close_type, direction, symbol, amount, trade_id)

    if not order.get("id"):
        print("❌ Falha ao enviar ordem.")
        return None

    return order

async def aguardar_resultado(timeout=60):
    global resultado_global
    print("⏳ Aguardando resultado do sinal...")
    for _ in range(timeout):
        if resultado_global in ["WIN", "LOSS", "GALE1", "GALE2"]:
            result = resultado_global
            resultado_global = None
            print(f"🎯 Resultado recebido após execução: {result}")
            return result
        await asyncio.sleep(1)
    print("⌛ Tempo esgotado aguardando resultado.")
    return None

async def executar_gale_com_timeout(n_gale, isDemo, close_type, direction, symbol, amount):
    print(f"🚨 Executando Gale {n_gale}")
    valor = amount * (2 ** n_gale)
    etapa = f"Gale {n_gale}"
    order = await tentar_ordem(isDemo, close_type, direction, symbol, valor, etapa)

    if not order:
        print(f"⚠️ Ordem da {etapa} não foi executada corretamente.")
        return

    result = await aguardar_resultado(70)

    if result == "WIN" or result == f"GALE{n_gale}":
        print(f"✅ WIN no {etapa}")
        await update_win_value(user_id=USER_ID, win_value=order['pnl'], brokerage_id=BROKERAGE_ID)
        await update_trade_order_info(order_id=order['id'], user_id=USER_ID, status=f"WON NA {etapa.upper()}", pnl=order['pnl'])
    else:
        print(f"❌ LOSS no {etapa}")
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
    global sinal_ativo, proxima_gale, resultado_global
    sinal_ativo = data
    proxima_gale = 1

    entrada = data["entry_time"]
    gale1 = data["gale1"]
    gale2 = data["gale2"]
    close_type = data["expiration"]
    direction = data["direction"]
    symbol = data["symbol"]

    print(f"\n🎯 Executando sinal: {symbol} | Direção: {direction} | Entrada: {entrada} | Expiração: {close_type}")

    bot_options = await get_bot_options(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    amount = bot_options['entry_price']
    isDemo = bot_options['is_demo']

    await aguardar_horario(entrada, "Entrada Principal")
    order = await tentar_ordem(isDemo, close_type, direction, symbol, amount, "Entrada Principal")

    if not order:
        print("❌ Falha na entrada principal.")
        return

    result = await aguardar_resultado()
    if result == "WIN":
        print("✅ WIN na Entrada Principal")
        await update_win_value(user_id=USER_ID, win_value=order['pnl'], brokerage_id=BROKERAGE_ID)
        await update_trade_order_info(order_id=order['id'], user_id=USER_ID, status="WON", pnl=order['pnl'])
        await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
        return

    print("❌ LOSS na Entrada Principal")

    if gale1:
        await aguardar_horario(gale1, "Gale 1")
        await executar_gale_com_timeout(1, isDemo, close_type, direction, symbol, amount)
        if resultado_global == "WIN" or resultado_global == "GALE1":
            return

    if gale2:
        await aguardar_horario(gale2, "Gale 2")
        await executar_gale_com_timeout(2, isDemo, close_type, direction, symbol, amount)

async def main():
    global resultado_global, sinal_ativo

    print("🚀 Iniciando conexão com RabbitMQ...")
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    print("✅ Conexão estabelecida com RabbitMQ")

    channel = await connection.channel()
    exchange = await channel.declare_exchange("avalon_signals", aio_pika.ExchangeType.FANOUT)
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange)

    print("📱 Aguardando sinais da fila...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                raw = message.body.decode()
                print(f"\n📨 Mensagem bruta recebida: {raw}")
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as e:
                    print("❌ Erro ao decodificar JSON:", e)
                    continue

                tipo = data.get("type")
                print(f"🔍 Tipo de mensagem: {tipo}")

                if tipo == "result":
                    resultado_global = data.get("result")
                    print(f"📊 Resultado recebido: {resultado_global}")

                elif tipo == "entry":
                    print("📥 Sinal de entrada recebido:", data)
                    await aguardar_e_executar_entradas(data)

                elif tipo == "gale_trigger":
                    gale = data.get("gale")
                    print(f"🔔 Trigger de GALE {gale} recebido (mas usando fallback de timeout)")

if __name__ == "__main__":
    asyncio.run(main())
