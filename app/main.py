from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import os
import re
import api
from datetime import datetime
import requests
import asyncio

load_dotenv()
TOKEN = os.getenv("TOKEN_TELEGRAN")
API_TOKEN = os.getenv("API_TOKEN")
USER_ID = os.getenv("USER_ID")

# Envia a ordem de compra e retorna o ID da operação
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

# Executa a ordem e verifica o resultado final
async def executar_ordem_e_verificar(isDemo, close_type, direction, symbol, amount):
    order = realizar_compra(isDemo, close_type, direction, symbol, amount)
    order_id = order.get("id")
    order_price = order.get("openPrice")
    order_status = order.get("result")

    if not order_id:
        print("❌ Falha ao enviar ordem.")
        return None

    await api.create_trade_order_info(user_id=USER_ID, order_id=order_id, symbol=symbol,
                                      order_type=direction, quantity=amount, price=order_price,
                                      status=order_status)

    url_status = f"https://broker-api.mybroker.dev/token/trades/{order_id}"
    headers = {"api-token": API_TOKEN}

    print(f"🔍 Verificando resultado da ordem {order_id}...")
    while True:
        await asyncio.sleep(10)
        try:
            response = requests.get(url_status, headers=headers)
            data = response.json()
            result = data.get("result") # Pode ser "WON", "LOST" ou "PENDING"
            print(f"📊 Status atual: {result}")
            if result in ["WON", "LOST"]:
                return data  # Retorna todos os dados da ordem
        except Exception as e:
            print(f"⚠️ Erro ao verificar status: {e}")

# Espera até o horário desejado
async def aguardar_horario(horario: str):
    print(f"⏳ Aguardando horário: {horario}")
    while True:
        agora = datetime.now().strftime("%H:%M")
        if agora == horario:
            return
        await asyncio.sleep(5)

# Controla a entrada principal e as gales
async def aguardar_e_executar_entradas(entrada: str, gale1: str, gale2: str,
                                       isDemo: bool, close_type: str,
                                       direction: str, symbol: str, amount: float):
    # Entrada principal
    await aguardar_horario(entrada)
    order = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, amount)

    bot_options = await api.get_bot_options(USER_ID)

    gale_one = bot_options['gale_one']
    gale_two = bot_options['gale_two']

    if not order:
        return

    result = order.get("result")
    pnl = order.get("pnl")

    if result == "WON":
        print("✅ Entrada principal venceu.")
        await api.update_win_value(USER_ID, pnl)
        await api.update_trade_order_info(order_id=order.get("id"), user_id=USER_ID, status="WON")
        return

    # Gale 1
    if result == "LOST" and gale1 and gale_one:
        await api.update_loss_value(USER_ID, amount)
        await aguardar_horario(gale1)
        gale1_valor = amount * 2
        order = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, gale1_valor)

        if not order:
            return

        result = order.get("result")
        pnl = order.get("pnl")

        if result == "WON":
            print("✅ Gale 1 venceu.")
            await api.update_win_value(USER_ID, pnl)
            await api.update_trade_order_info(order_id=order.get("id"), user_id=USER_ID, status="WON NA GALE 1")

    # Gale 2
    if result == "LOST" and gale2 and gale_two:
        await api.update_loss_value(USER_ID, gale1_valor)
        await aguardar_horario(gale2)
        gale2_valor = amount * 4
        order = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, gale2_valor)

        if not order:
            return

        result = order.get("result")
        pnl = order.get("pnl")

        if result == "WON":
            print("✅ Gale 2 venceu.")
            await api.update_win_value(USER_ID, pnl)
            await api.update_trade_order_info(order_id=order.get("id"), user_id=USER_ID, status="WON NA GALE 2")
        elif result == "LOST":
            print("❌ Gale 2 perdeu.")
            await api.update_loss_value(USER_ID, gale2_valor)
            await api.update_trade_order_info(order_id=order.get("id"), user_id=USER_ID, status="LOST")

# Trata mensagens do grupo
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and "✅ ENTRADA CONFIRMADA ✅" in update.message.text:
        text = update.message.text

        # Extrair os dados com regex
        ativo_match = re.search(r"Ativo:\s*(.+)", text)
        expiracao_match = re.search(r"Expiração:\s*(.+)", text)
        entrada_match = re.search(r"Entrada:\s*(\d{2}:\d{2})", text)
        direcao_match = re.search(r"Direção:\s*[\S]+\s+([A-Z]+)", text)
        gales_match = re.findall(r"\dº GALE: TERMINA EM: (\d{2}:\d{2})", text)

        ativo = ativo_match.group(1).strip() if ativo_match else None
        expiracao = expiracao_match.group(1).strip() if expiracao_match else None
        entrada = entrada_match.group(1).strip() if entrada_match else None
        direcao = direcao_match.group(1).strip() if direcao_match else None
        gale1 = gales_match[0] if len(gales_match) > 0 else None
        gale2 = gales_match[1] if len(gales_match) > 1 else None

        if expiracao == "M1":
            expiracao = "01:00"
        elif expiracao == "M5":
            expiracao = "05:00"

        if direcao == "COMPRA":
            direcao = "BUY"
        elif direcao == "VENDA":
            direcao = "SELL"

        print("📥 Novo sinal detectado:")
        print(f"Ativo: {ativo}")
        print(f"Expiração: {expiracao}")
        print(f"Entrada: {entrada}")
        print(f"Direção: {direcao}")
        print(f"Gale 1: {gale1}")
        print(f"Gale 2: {gale2}")


        bot_options = await api.get_bot_options(update.effective_user.id)
        valor_base = bot_options['entry_price']
        is_demo = bot_options['is_demo']

        asyncio.create_task(aguardar_e_executar_entradas(
            entrada=entrada,
            gale1=gale1,
            gale2=gale2,
            isDemo=is_demo,
            close_type=expiracao,
            direction=direcao,
            symbol=ativo,
            amount=valor_base
        ))

# Inicia o bot
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, handle_message))
app.run_polling()


