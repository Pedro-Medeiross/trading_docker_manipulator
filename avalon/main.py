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
sinais_recebidos = asyncio.Queue()
lock = asyncio.Lock()

# --------- Broker utils ---------

async def consultar_balance(isDemo: bool):
    url = "http://avalon_api:3001/api/account/balance"
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

async def realizar_compra(isDemo: bool, timeframe_minutes: int, direction: str, symbol: str, amount: float):
    """Envia ordem imediata (digital) com período = timeframe_minutes * 60."""
    url = 'http://avalon_api:3001/api/trade/digital/buy'
    api_direction = "CALL" if direction == "BUY" else "PUT"
    period_seconds = int(timeframe_minutes) * 60

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
    print(f"➡️ Enviando ordem: {payload}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                if response.status == 201 and "order" in data:
                    print("✅ Ordem enviada com sucesso.")
                    print(f"🕒 {datetime.now(pytz.timezone('America/Sao_Paulo')).isoformat()}")
                    return {
                        "result": data.get("message", ""),
                        "openPrice": data.get("order", {}).get("id", 0)
                    }
                else:
                    print(f"⚠️ Ordem não foi aceita: {data}")
        except Exception as e:
            print(f"❌ Erro na ordem: {e}")
    return None

# --------- Resultado & PNL ---------

async def aguardar_resultado():
    """
    Aguarda indefinidamente até receber um 'result' com WIN ou LOSS.
    (Sem timeout, conforme solicitado)
    """
    global resultado_global
    print("⏳ Aguardando RESULTADO (WIN/LOSS) sem timeout...")
    while True:
        data = await sinais_recebidos.get()
        if data.get("type") == "result":
            r = data.get("result", "").upper()
            if r in ("WIN", "LOSS"):
                resultado_global = r
                print(f"📥 RESULTADO recebido: {resultado_global}")
                return resultado_global
        # ignora outros tipos

async def calcular_pnl(ordem, isDemo):
    """
    Se WIN: confirma por aumento do saldo (até 5 tentativas x 10s).
    Se LOSS: registra perda imediata.
    """
    global resultado_global
    balance_before = ordem["balance_before"]
    amount = ordem["amount"]
    print(f"📊 Saldo antes da operação: {balance_before}")

    if resultado_global == "LOSS":
        print("❌ Resultado LOSS — registrando perda.")
        ordem["pnl"] = amount
        await update_loss_value(USER_ID, amount, BROKERAGE_ID)
        await update_trade_order_info(ordem["id"], USER_ID, "LOST", amount)
        await verify_stop_values(USER_ID, BROKERAGE_ID)
        return -amount

    if resultado_global != "WIN":
        print("ℹ️ Resultado indefinido — PNL 0.")
        ordem["pnl"] = 0
        await update_trade_order_info(ordem["id"], USER_ID, "PENDING (sem resultado)", 0)
        return 0

    print("✅ Resultado WIN — verificando saldo para confirmar PNL...")
    for tentativa in range(1, 6):  # 5 tentativas / 10s
        await asyncio.sleep(10)
        balance_after = await consultar_balance(isDemo)
        if balance_after is None:
            print(f"⚠️ Tentativa {tentativa}: não foi possível ler o saldo.")
            continue

        print(f"⏱️ Tentativa {tentativa} - Saldo: {balance_after}")
        if balance_after > balance_before:
            pnl = round(balance_after - balance_before, 2)
            ordem["pnl"] = pnl
            print(f"📈 PNL confirmado: {pnl:.2f}")
            await update_win_value(USER_ID, pnl, BROKERAGE_ID)
            await update_trade_order_info(ordem["id"], USER_ID, "WON", pnl)
            await verify_stop_values(USER_ID, BROKERAGE_ID)
            return pnl

        if balance_after < balance_before:
            print("❌ Saldo caiu mesmo com WIN — reclassificando LOSS.")
            resultado_global = "LOSS"
            loss = amount
            ordem["pnl"] = loss
            await update_loss_value(USER_ID, loss, BROKERAGE_ID)
            await update_trade_order_info(ordem["id"], USER_ID, "LOST (saldo caiu com WIN)", loss)
            await verify_stop_values(USER_ID, BROKERAGE_ID)
            return -loss

    print("⚠️ Saldo não mudou após WIN — reclassificando LOSS.")
    resultado_global = "LOSS"
    loss = amount
    ordem["pnl"] = loss
    await update_loss_value(USER_ID, loss, BROKERAGE_ID)
    await update_trade_order_info(ordem["id"], USER_ID, "LOST (saldo inalterado após WIN)", loss)
    await verify_stop_values(USER_ID, BROKERAGE_ID)
    return -loss

# --------- Execução ---------

async def enviar_ordem_imediata(data):
    """
    Payload esperado do publisher:
    {
      "type": "entry",
      "symbol": "EURUSD",
      "timeframe_minutes": 1|5,
      "direction": "BUY"|"SELL",
      (opcional) "expiration": "01:00"
    }
    """
    global resultado_global
    resultado_global = None  # zera estado

    symbol = data["symbol"]
    direction = data["direction"]
    timeframe = int(data.get("timeframe_minutes") or 1)

    bot_options = await get_bot_options(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    amount = float(bot_options["entry_price"])
    isDemo = bool(bot_options["is_demo"])
    is_auto = bool(bot_options.get("is_auto", False))  # 🔹 pega is_auto

    print("🚀 ENTRADA IMEDIATA (AVALON)")
    print("──────────────────────────────────────────────")
    print(f"📈 Ativo: {symbol}")
    print(f"🎯 Direção: {direction} | Timeframe: {timeframe} min")
    print(f"💰 Valor: {amount} | Conta: {'DEMO' if isDemo else 'REAL'}")
    print(f"⚙️ Modo: {'AUTO' if is_auto else 'MANUAL'} (sem gales)")
    print("──────────────────────────────────────────────")

    trade_id = str(uuid.uuid4())
    balance_before = await consultar_balance(isDemo)

    trade = await realizar_compra(isDemo, timeframe, direction, symbol, amount)
    if not trade:
        print("❌ Ordem não enviada. Abortando.")
        return

    await create_trade_order_info(
        user_id=USER_ID,
        order_id=trade_id,
        symbol=symbol,
        order_type=direction,
        quantity=amount,
        price=0,
        status="PENDING",
        brokerage_id=BROKERAGE_ID
    )

    ordem = {
        "id": trade_id,
        "balance_before": balance_before,
        "amount": amount,
        "pnl": 0,
        **trade
    }

    # 🧭 Aguarda resultado (sem timeout)
    await aguardar_resultado()

    # 💰 Calcula/atualiza PNL conforme resultado
    await calcular_pnl(ordem, isDemo)

async def processar_entrada(data):
    async with lock:
        await enviar_ordem_imediata(data)

# --------- Main / Rabbit ---------

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
                data = json.loads(message.body.decode())
                tipo = data.get("type")
                timestamp = datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat()

                if tipo == "entry":
                    print("📨 NOVO SINAL RECEBIDO")
                    print("──────────────────────────────────────────────")
                    print(f"🕒 Horário: {timestamp}")
                    print(f"📦 Payload: {json.dumps(data, ensure_ascii=False)}")
                    print("──────────────────────────────────────────────")
                    asyncio.create_task(processar_entrada(data))

                elif tipo == "result":
                    print("📩 RESULT RECEBIDO")
                    print("──────────────────────────────────────────────")
                    print(f"🕒 Horário: {timestamp}")
                    print(f"📦 {json.dumps(data, ensure_ascii=False)}")
                    print("──────────────────────────────────────────────")
                    await sinais_recebidos.put(data)

                else:
                    print(f"ℹ️ Mensagem ignorada (tipo: {tipo}).")

if __name__ == "__main__":
    asyncio.run(main())
