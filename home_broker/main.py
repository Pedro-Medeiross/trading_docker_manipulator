import os
import json
import asyncio
import aio_pika
import aiohttp
import base64
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

load_dotenv()

USER_ID = os.getenv("USER_ID")
BROKERAGE_ID = os.getenv("BROKERAGE_ID")

# credenciais Home Broker
HB_USERNAME = os.getenv("HB_USERNAME")
HB_PASSWORD = os.getenv("HB_PASSWORD")
HB_ROLE = "hbb"
HB_LOGIN_APP = os.getenv("HB_LOGIN_APP")
HB_PASSWORD_APP = os.getenv("HB_PASSWORD_APP")

# RabbitMQ
host = os.getenv("RABBITMQ_HOST")
user = os.getenv("RABBITMQ_USER")
password = os.getenv("RABBITMQ_PASS")
RABBITMQ_URL = f"amqp://{user}:{password}@{host}:5672/"

print("🔗 RabbitMQ URL:", RABBITMQ_URL)

# variáveis de sessão
ACCESS_TOKEN = None
REFRESH_TOKEN = None


async def login_homebroker():
    """Realiza login e atualiza tokens globais"""
    global ACCESS_TOKEN, REFRESH_TOKEN
    url = "https://bot-account-manager-api.homebroker.com/v3/login"

    auth_string = f"{HB_LOGIN_APP}:{HB_PASSWORD_APP}"
    basic_auth = base64.b64encode(auth_string.encode()).decode()

    headers = {"Authorization": f"Basic {basic_auth}", "Content-Type": "application/json"}
    body = {
        "username": HB_USERNAME,
        "password": HB_PASSWORD,
        "role": HB_ROLE
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as resp:
            if resp.status == 200:
                data = await resp.json()
                ACCESS_TOKEN = data["access_token"]
                REFRESH_TOKEN = data["refresh_token"]
                print("✅ Login realizado com sucesso")
                return True
            else:
                print(f"❌ Falha no login: {resp.status}")
                return False


async def ensure_login():
    """Garante que o token está válido, caso contrário reloga"""
    global ACCESS_TOKEN
    if not ACCESS_TOKEN:
        return await login_homebroker()
    # opcional: validar expiração do JWT
    return True


async def realizar_compra(isDemo: bool, close_type: str, direction: str, symbol: str, amount: float, start_time: str):
    """Abre ordem na Home Broker"""
    await ensure_login()

    url = "https://trade-api-edge.homebroker.com/op"
    payload = {
        "id": f"op-{datetime.utcnow().timestamp()}",
        "direction": direction,
        "bet_value_usd_cents": int(amount * 100),
        "duration_milliseconds": int(close_type) * 60000,
        "start_time_utc": start_time,
        "ticker_symbol": symbol,
        "account_type": "demo" if isDemo else "real",
        "currency": "BRL"
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print("📤 Ordem enviada:", data)
                    # Criar registro da ordem imediatamente
                    await create_trade_order_info(
                        user_id=USER_ID,
                        order_id=data["id"],
                        symbol=symbol,
                        order_type=direction,
                        quantity=amount,
                        price=None,  # preço não fornecido pelo HB
                        status="OPEN",
                        brokerage_id=BROKERAGE_ID
                    )
                    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
                    return data
                else:
                    print(f"❌ Erro ao enviar ordem: status {resp.status}")
                    return {}
        except Exception as e:
            print(f"⚠️ Erro ao enviar ordem: {e}")
            return {}


async def verificar_resultado(op_id: str, etapa: str):
    """Consulta resultado da operação"""
    await ensure_login()
    url = f"https://bot-trade-api.homebroker.com/op/get/{op_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(5)
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result")
                    print(f"📊 Status {etapa}: {result}")
                    if result in ["Gain", "Loss", "Draw"]:
                        return data
                else:
                    print(f"⚠️ Erro ao checar ordem {op_id}: {resp.status}")


async def aguardar_horario(horario: str, etapa: str):
    print(f"⏳ Aguardando horário {horario} ({etapa})")
    tz_brasilia = pytz.timezone("America/Sao_Paulo")
    target_time = datetime.strptime(horario, "%H:%M").time()
    while True:
        agora = datetime.now(tz_brasilia).time()
        if agora >= target_time:
            return
        await asyncio.sleep(1)


async def aguardar_e_executar_entradas(data):
    entrada = data["entry_time"]
    gale1 = data.get("gale1")
    gale2 = data.get("gale2")
    close_type = data["expiration"]
    direction = data["direction"]
    symbol = data["symbol"]

    bot_options = await get_bot_options(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    amount = bot_options["entry_price"]
    isDemo = bot_options["is_demo"]
    gale_one_value = bot_options.get("gale_one_value")
    gale_two_value = bot_options.get("gale_two_value")
    is_auto = bot_options.get("is_auto")

    # Entrada principal
    await aguardar_horario(entrada, "Entrada Principal")
    order = await realizar_compra(isDemo, close_type, direction, symbol, amount, datetime.utcnow().isoformat() + "Z")

    if not order.get("id"):
        print("❌ Falha ao abrir ordem principal")
        return

    op_id = order["id"]
    result_data = await verificar_resultado(op_id, "Entrada Principal")
    result = result_data.get("result")
    pnl = result_data.get("profit_usd_cents", 0) / 100

    if result == "Gain":
        await update_win_value(user_id=USER_ID, win_value=pnl, brokerage_id=BROKERAGE_ID)
        await update_trade_order_info(order_id=op_id, user_id=USER_ID, status="WON", pnl=pnl)
        await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
        return

    await update_loss_value(user_id=USER_ID, loss_value=amount, brokerage_id=BROKERAGE_ID)
    await update_trade_order_info(order_id=op_id, user_id=USER_ID, status="LOST", pnl=pnl)
    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)

    if is_auto:
        # Gale 1
        if (result in ["Loss", "Draw"]) and gale1 and gale_one_value:
            await aguardar_horario(gale1, "Gale 1")
            order_g1 = await realizar_compra(isDemo, close_type, direction, symbol, gale_one_value, datetime.utcnow().isoformat() + "Z")
            if order_g1.get("id"):
                res_g1 = await verificar_resultado(order_g1["id"], "Gale 1")
                res_g1_pnl = res_g1.get("profit_usd_cents", 0) / 100
                if res_g1.get("result") == "Gain":
                    await update_win_value(user_id=USER_ID, win_value=res_g1_pnl, brokerage_id=BROKERAGE_ID)
                    await update_trade_order_info(order_id=order_g1["id"], user_id=USER_ID, status="WON NA GALE 1", pnl=res_g1_pnl)
                    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
                else:
                    await update_loss_value(user_id=USER_ID, loss_value=gale_one_value, brokerage_id=BROKERAGE_ID)
                    await update_trade_order_info(order_id=order_g1["id"], user_id=USER_ID, status="LOST", pnl=res_g1_pnl)
                    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)

        # Gale 2
        if (result in ["Loss", "Draw"]) and gale2 and gale_two_value:
            await aguardar_horario(gale2, "Gale 2")
            order_g2 = await realizar_compra(isDemo, close_type, direction, symbol, gale_two_value, datetime.utcnow().isoformat() + "Z")
            if order_g2.get("id"):
                res_g2 = await verificar_resultado(order_g2["id"], "Gale 2")
                res_g2_pnl = res_g2.get("profit_usd_cents", 0) / 100
                if res_g2.get("result") == "Gain":
                    await update_win_value(user_id=USER_ID, win_value=res_g2_pnl, brokerage_id=BROKERAGE_ID)
                    await update_trade_order_info(order_id=order_g2["id"], user_id=USER_ID, status="WON NA GALE 2", pnl=res_g2_pnl)
                    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
                else:
                    await update_loss_value(user_id=USER_ID, loss_value=gale_two_value, brokerage_id=BROKERAGE_ID)
                    await update_trade_order_info(order_id=order_g2["id"], user_id=USER_ID, status="LOST", pnl=res_g2_pnl)
                    await verify_stop_values(user_id=USER_ID, brokerage_id=BROKERAGE_ID)
    else:
        print("📌 Modo manual: não executando gales.")


# consumer
async def main():
    await login_homebroker()
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange("xofre_signals", aio_pika.ExchangeType.FANOUT)
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
