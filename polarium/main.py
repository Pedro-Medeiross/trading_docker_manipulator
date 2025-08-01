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
etapa_em_andamento = None
sinais_recebidos = asyncio.Queue()


async def limpar_sdk_cache():
    url = "http://polarium_api:3002/api/sdk/stop"
    headers = {"Content-Type": "application/json"}
    payload = {"email": BROKERAGE_USERNAME}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    print("♻️ SDK removido do cache com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao limpar cache SDK: {e}")


async def consultar_balance(isDemo: bool):
    await limpar_sdk_cache()
    url = "http://polarium_api:3002/api/account/balance"
    headers = {"Content-Type": "application/json"}
    payload = {"email": BROKERAGE_USERNAME, "password": BROKERAGE_PASSWORD}
    account_type = "demo" if isDemo else "real"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    for wallet in data.get("balances", []):
                        if wallet["type"] == account_type:
                            return wallet["amount"]
    except Exception as e:
        print(f"❌ Erro ao consultar saldo: {e}")
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
                if response.status == 201 and "Digital option purchase initiated." in data.get("message", ""):
                    print("✅ Ordem enviada com sucesso.")
                    return {"status": "enviada", "data": data}
                else:
                    print(f"⚠️ Ordem não foi aceita: {data}")
        except Exception as e:
            print(f"❌ Erro na ordem: {e}")
    return None


async def tentar_ordem(isDemo, close_type, direction, symbol, amount, etapa):
    print(f"🟡 {etapa.upper()} - Enviando ordem de {amount} em {symbol} ({direction})")
    trade_id = str(uuid.uuid4())
    balance_before = await consultar_balance(isDemo)
    trade = await realizar_compra(isDemo, close_type, direction, symbol, amount)

    if not trade:
        print("❌ Ordem falhou. Etapa será cancelada.")
        return None

    await create_trade_order_info(user_id=USER_ID, order_id=trade_id, symbol=symbol, order_type=direction,
                                  quantity=amount, price=0, status="PENDING", brokerage_id=BROKERAGE_ID)

    return {
        "id": trade_id,
        "balance_before": balance_before,
        "pnl": 0,
        **trade
    }


async def calcular_pnl(ordem, isDemo):
    balance_before = ordem["balance_before"]
    timeout = 55
    elapsed = 0
    balance_after = await consultar_balance(isDemo)

    if resultado_global == "WIN":
        while balance_after <= balance_before and elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            balance_after = await consultar_balance(isDemo)
        if balance_after <= balance_before:
            print("⚠️ Saldo não aumentou após WIN. PNL será registrado como 0.")
            ordem["pnl"] = 0
            return 0

    pnl = round(balance_after - balance_before, 2)
    ordem["pnl"] = pnl
    print(f"📈 PNL final: {pnl:.2f}")
    return pnl


async def aguardar_resultado_ou_gale(etapa):
    global resultado_global
    sinais_validos = {
        "entry": ["WIN", "LOSS", "GALE 1"],
        "gale1": ["WIN", "LOSS", "GALE 2"],
        "gale2": ["WIN", "LOSS"]
    }
    while True:
        data = await sinais_recebidos.get()
        tipo = data.get("type")
        resultado = f"GALE {data['step']}" if tipo == "gale" else data.get("result")
        if resultado in sinais_validos[etapa]:
            resultado_global = resultado
            print(f"📥 Resultado aceito para etapa {etapa.upper()}: {resultado}")
            return resultado
        else:
            print(f"⚠️ Resultado ignorado ({resultado}) fora da etapa {etapa.upper()}")


async def aguardar_horario(horario, etapa):
    tz = pytz.timezone("America/Sao_Paulo")
    target = datetime.strptime(horario, "%H:%M").time()
    print(f"⏳ Aguardando {etapa.upper()}: {horario}")
    while True:
        now = datetime.now(tz).time()
        if now >= target:
            print(f"⏰ Executando {etapa.upper()}")
            return
        await asyncio.sleep(1)


async def aguardar_e_executar_entradas(data):
    global etapa_em_andamento
    symbol = data["symbol"]
    direction = data["direction"]
    close_type = data["expiration"]
    entrada = data["entry_time"]
    gale1 = data.get("gale1")
    gale2 = data.get("gale2")

    bot_options = await get_bot_options(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    amount = bot_options['entry_price']
    isDemo = bot_options['is_demo']
    gale1_enabled = bot_options.get("gale_one", False)
    gale2_enabled = bot_options.get("gale_two", False)

    # ENTRADA PRINCIPAL
    etapa_em_andamento = "entry"
    await aguardar_horario(entrada, "Entrada Principal")
    ordem = await tentar_ordem(isDemo, close_type, direction, symbol, amount, "Entrada Principal")
    if not ordem:
        print("❌ Falha na entrada principal. Abortando.")
        return
    resultado = await aguardar_resultado_ou_gale("entry")

    if resultado == "WIN":
        await calcular_pnl(ordem, isDemo)
        await update_win_value(USER_ID, ordem["pnl"], BROKERAGE_ID)
        await update_trade_order_info(ordem["id"], USER_ID, "WON", ordem["pnl"])
        await verify_stop_values(USER_ID, BROKERAGE_ID)
        return

    if resultado in ["LOSS", "GALE 1"]:
        if not gale1 or not gale1_enabled:
            print("❌ GALE 1 não habilitada. Finalizando como LOSS.")
            loss = amount
            ordem["pnl"] = loss
            await update_loss_value(USER_ID, loss, BROKERAGE_ID)
            await update_trade_order_info(ordem["id"], USER_ID, "LOST", loss)
            await verify_stop_values(USER_ID, BROKERAGE_ID)
            return

        # GALE 1
        etapa_em_andamento = "gale1"
        await aguardar_horario(gale1, "Gale 1")
        ordem = await tentar_ordem(isDemo, close_type, direction, symbol, amount * 2, "Gale 1")
        if not ordem:
            print("❌ Falha ao executar GALE 1. Abortando operação.")
            return
        resultado = await aguardar_resultado_ou_gale("gale1")

        if resultado == "WIN":
            await calcular_pnl(ordem, isDemo)
            await update_win_value(USER_ID, ordem["pnl"], BROKERAGE_ID)
            await update_trade_order_info(ordem["id"], USER_ID, "WON NA GALE 1", ordem["pnl"])
            await verify_stop_values(USER_ID, BROKERAGE_ID)
            return

        if resultado in ["LOSS", "GALE 2"]:
            if not gale2 or not gale2_enabled:
                print("❌ GALE 2 não habilitada. Finalizando GALE 1 como LOSS.")
                loss = amount * 2
                ordem["pnl"] = loss
                await update_loss_value(USER_ID, loss, BROKERAGE_ID)
                await update_trade_order_info(ordem["id"], USER_ID, "LOST", loss)
                await verify_stop_values(USER_ID, BROKERAGE_ID)
                return

            # GALE 2
            etapa_em_andamento = "gale2"
            await aguardar_horario(gale2, "Gale 2")
            ordem = await tentar_ordem(isDemo, close_type, direction, symbol, amount * 4, "Gale 2")
            if not ordem:
                print("❌ Falha ao executar GALE 2. Abortando.")
                return
            resultado = await aguardar_resultado_ou_gale("gale2")

            if resultado == "WIN":
                await calcular_pnl(ordem, isDemo)
                await update_win_value(USER_ID, ordem["pnl"], BROKERAGE_ID)
                await update_trade_order_info(ordem["id"], USER_ID, "WON NA GALE 2", ordem["pnl"])
                await verify_stop_values(USER_ID, BROKERAGE_ID)
            else:
                print("❌ Resultado final: LOSS na GALE 2.")
                loss = amount * 4
                ordem["pnl"] = loss
                await update_loss_value(USER_ID, loss, BROKERAGE_ID)
                await update_trade_order_info(ordem["id"], USER_ID, "LOST", loss)
                await verify_stop_values(USER_ID, BROKERAGE_ID)


async def main():
    print("🔌 Conectando ao RabbitMQ...")
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange("avalon_signals", aio_pika.ExchangeType.FANOUT)
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange)
    print("✅ Conectado e aguardando sinais...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    data = json.loads(message.body.decode())
                    tipo = data.get("type")
                    if tipo == "entry":
                        print("📨 Novo sinal de entrada recebido")
                        print(data)
                        asyncio.create_task(aguardar_e_executar_entradas(data))
                    elif tipo in ["result", "gale"]:
                        await sinais_recebidos.put(data)
                        print(data)
                except Exception as e:
                    print(f"❌ Erro ao processar mensagem: {e}")


if __name__ == "__main__":
    asyncio.run(main())
