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

resultado_global = None
proxima_etapa = asyncio.Event()
etapa_atual = None
etapa_em_andamento = None


async def limpar_sdk_cache():
    url = "http://avalon_api:3001/api/sdk/stop"
    headers = {"Content-Type": "application/json"}
    payload = {"email": BROKERAGE_USERNAME}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    print("♻️ SDK removido do cache com sucesso.")
                else:
                    print(f"⚠️ Falha ao remover SDK do cache: Status {response.status}")
    except Exception as e:
        print(f"❌ Erro ao tentar remover SDK do cache: {e}")


async def consultar_balance(isDemo: bool):
    await limpar_sdk_cache()
    url = "http://avalon_api:3001/api/account/balance"
    headers = {"Content-Type": "application/json"}
    payload = {"email": BROKERAGE_USERNAME, "password": BROKERAGE_PASSWORD}
    account_type = "demo" if isDemo else "real"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"🔍 Resposta da API de saldo: {data}")
                    for wallet in data.get("balances", []):
                        if wallet["type"] == account_type:
                            return wallet["amount"]
                    print(f"⚠️ Tipo de carteira '{account_type}' não encontrado na resposta.")
                else:
                    print(f"❌ Erro ao consultar saldo: Status {response.status}")
                    text = await response.text()
                    print(f"📄 Corpo da resposta: {text}")
    except Exception as e:
        print(f"❌ Erro de conexão com API de saldo: {e}")
    return None


async def realizar_compra(isDemo, close_type, direction, symbol, amount):
    url = 'http://avalon_api:3001/api/trade/digital/buy'
    api_direction = "CALL" if direction == "BUY" else "PUT"
    minutes, seconds = map(int, close_type.split(":"))
    period_seconds = minutes * 60 + seconds
    payload = {
        "email": BROKERAGE_USERNAME,
        "password": BROKERAGE_PASSWORD,
        "assetName": symbol,
        "operationValue": float(amount),
        "direction": api_direction,
        "account_type": "demo" if isDemo else "real",
        "period": period_seconds
    }
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                if response.status == 201:
                    return {
                        "result": data.get("status", ""),
                        "openPrice": data.get("open_price", 0)
                    }
        except Exception as e:
            print(f"❌ Erro na requisição da ordem: {e}")
    return {}


async def tentar_ordem(isDemo, close_type, direction, symbol, amount, etapa):
    print(f"🟡 {etapa.upper()} - Enviando ordem de {amount} em {symbol} ({direction})")
    trade_id = str(uuid.uuid4())
    balance_before = await consultar_balance(isDemo)
    print(f"💰 Saldo antes da operação: {balance_before:.2f}" if balance_before is not None else "⚠️ Saldo antes indisponível")
    await create_trade_order_info(user_id=USER_ID, order_id=trade_id, symbol=symbol, order_type=direction,
                                  quantity=amount, price=0, status="PENDING", brokerage_id=BROKERAGE_ID)
    trade = await realizar_compra(isDemo, close_type, direction, symbol, amount)
    if not trade:
        return None
    return {
        "id": trade_id,
        "balance_before": balance_before,
        "pnl": 0,
        **trade
    }


async def calcular_pnl(ordem, isDemo):
    global resultado_global
    balance_before = ordem["balance_before"]
    timeout = 45
    elapsed = 0
    balance_after = await consultar_balance(isDemo)

    print("\n================ DEBUG PNL ==================")
    print(f"Resultado recebido: {resultado_global}")
    print(f"Saldo antes da operação: {balance_before:.2f}")
    print(f"Saldo após 1ª consulta pós-operação: {balance_after:.2f}")

    if resultado_global == "WIN":
        print("⏳ Esperando saldo aumentar (WIN)...")
        while balance_after <= balance_before and elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            balance_after = await consultar_balance(isDemo)
        if balance_after <= balance_before:
            print("⚠️ Saldo não aumentou após WIN. Reclassificando como LOSS.")
            resultado_global = "LOSS"

    elif resultado_global in ["LOSS", "GALE 1", "GALE 2"]:
        print("⏳ Esperando saldo diminuir (perda)...")
        while balance_after == balance_before and elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            balance_after = await consultar_balance(isDemo)

    pnl = round(balance_after - balance_before, 2)
    ordem["pnl"] = pnl
    print(f"✅ Saldo final após polling: {balance_after:.2f}")
    print(f"📈 PNL calculado: {pnl:.2f}")
    print("============================================\n")
    return pnl


async def aguardar_horario(horario, etapa):
    tz = pytz.timezone("America/Sao_Paulo")
    target = datetime.strptime(horario, "%H:%M").time()
    print(f"⏳ Aguardando horário de {etapa.upper()}: {horario}")
    while True:
        now = datetime.now(tz).time()
        if now >= target:
            print(f"⏰ Executando {etapa.upper()}")
            return
        await asyncio.sleep(5)


async def aguardar_resultado_ou_gale():
    global resultado_global, proxima_etapa, etapa_atual, etapa_em_andamento
    await proxima_etapa.wait()
    proxima_etapa.clear()
    resultado = resultado_global
    resultado_global = None
    print("📥 =================== SINAL RECEBIDO ===================")
    print(f"📬 Tipo de sinal: {resultado}")
    print(f"🔄 Etapa atual: {etapa_atual}")
    print(f"🧩 Etapa em andamento: {etapa_em_andamento}")
    print("========================================================\n")
    return resultado


async def main():
    global resultado_global, proxima_etapa
    print("🔌 Conectando ao RabbitMQ...")
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange("avalon_signals", aio_pika.ExchangeType.FANOUT)
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange)
    print("✅ Conectado ao RabbitMQ e aguardando sinais...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    data = json.loads(message.body.decode())
                    tipo = data.get("type")

                    if tipo == "entry":
                        print("📨 Novo sinal de entrada recebido")
                        asyncio.create_task(aguardar_e_executar_entradas(data))

                    elif tipo == "result":
                        resultado_global = data.get("result")
                        proxima_etapa.set()

                    elif tipo == "gale":
                        step = data.get("step")
                        resultado_global = f"GALE {step}"
                        proxima_etapa.set()

                except Exception as e:
                    print(f"❌ Erro ao processar mensagem: {e}")


if __name__ == "__main__":
    asyncio.run(main())