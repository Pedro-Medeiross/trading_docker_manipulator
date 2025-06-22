from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import os
import re
import api
from datetime import datetime
import pytz
import requests
import asyncio

load_dotenv()
TOKEN = os.getenv("TOKEN_TELEGRAN")
API_TOKEN = os.getenv("API_TOKEN")
USER_ID = os.getenv("USER_ID")
BROKERAGE_ID = os.getenv("BROKERAGE_ID")

print("🔧 Configurações do Bot:")
print(f"Token: {TOKEN}")
print(f"API Token: {API_TOKEN}")
print(f"User ID: {USER_ID}")
print(f"Brokerage ID: {BROKERAGE_ID}")

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
async def executar_ordem_e_verificar(isDemo, close_type, direction, symbol, amount, etapa):
    order = realizar_compra(isDemo, close_type, direction, symbol, amount)
    order_id = order.get("id")
    order_price = order.get("openPrice")
    order_status = order.get("result")

    if not order_id:
        print("❌ Falha ao enviar ordem.")
        return None

    await api.create_trade_order_info(user_id=USER_ID, order_id=order_id, symbol=symbol,
                                      order_type=direction, quantity=amount, price=order_price,
                                      status=order_status, brokerage_id=BROKERAGE_ID)

    url_status = f"https://broker-api.mybroker.dev/token/trades/{order_id}"
    headers = {"api-token": API_TOKEN}

    print(f"🔍 Verificando resultado da ordem {order_id} para {etapa}...")
    while True:
        await asyncio.sleep(5)
        try:
            response = requests.get(url_status, headers=headers)
            data = response.json()
            result = data.get("result") # Pode ser "WON", "LOST", "DRAW" ou "PENDING"
            print(f"📊 Status atual: {result}")
            if result in ["WON", "LOST", "DRAW"]:
                return data  # Retorna todos os dados da ordem
        except Exception as e:
            print(f"⚠️ Erro ao verificar status: {e}")

# Espera até o horário desejado
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

# Controla a entrada principal e as gales
async def aguardar_e_executar_entradas(entrada: str, gale1: str, gale2: str,
                                       isDemo: bool, close_type: str,
                                       direction: str, symbol: str, amount: float):  # <-- adicione USER_ID como argumento
    await aguardar_horario(entrada, etapa="Entrada Principal")
    order = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, amount, etapa="Entrada Principal")

    if not order:
        print("⚠️ Falha na execução da entrada principal.")
        return

    bot_options = await api.get_bot_options(USER_ID)
    gale_one = bot_options['gale_one']
    gale_two = bot_options['gale_two']

    result = order.get("result")
    pnl = order.get("pnl")

    if result == "WON":
        print("✅ Entrada principal venceu.")
        print("atualizando valores de ganho...")
        await api.update_win_value(USER_ID, pnl)
        print("atualizando ordem...")
        await api.update_trade_order_info(order.get("id"), USER_ID, "WON")
        print("verificando valores de stop...")
        await api.verify_stop_values(USER_ID)
        return

    if result == "LOST" or result == "DRAW" and gale1 and gale_one:
        print("❌ Entrada principal perdeu, iniciando Gale 1...")
        print("atualizando valores de perda...")
        await api.update_loss_value(USER_ID, amount)
        print("atualizando ordem...")
        await api.update_trade_order_info(order.get("id"), USER_ID, "LOST")
        print("verificando valores de stop...")
        await api.verify_stop_values(USER_ID)

        await aguardar_horario(gale1, etapa="Gale 1")
        gale1_valor = amount * 2
        order_gale1 = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, gale1_valor, etapa="Gale 1")

        if not order_gale1:
            print("⚠️ Falha na execução da Gale 1.")
            return

        result_gale1 = order_gale1.get("result")
        pnl = order_gale1.get("pnl")

        if result_gale1 == "WON":
            print("✅ Gale 1 venceu.")
            print("atualizando valores de ganho...")
            await api.update_win_value(USER_ID, pnl)
            print("atualizando ordem...")
            await api.update_trade_order_info(order_gale1.get("id"), USER_ID, "WON NA GALE 1")
            print("verificando valores de stop...")
            await api.verify_stop_values(USER_ID)
            return

        if result_gale1 == "LOST" or result_gale1 == "DRAW" and gale2 and gale_two:
            print("❌ Gale 1 perdeu, iniciando Gale 2...")
            print("atualizando valores de perda...")
            await api.update_loss_value(USER_ID, gale1_valor)
            print("atualizando ordem...")
            await api.update_trade_order_info(order_gale1.get("id"), USER_ID, "LOST")
            print("verificando valores de stop...")
            await api.verify_stop_values(USER_ID)

            await aguardar_horario(gale2, etapa="Gale 2")
            gale2_valor = amount * 4
            order_gale2 = await executar_ordem_e_verificar(isDemo, close_type, direction, symbol, gale2_valor, etapa="Gale 2")

            if not order_gale2:
                print("⚠️ Falha na execução da Gale 2.")
                return

            result_gale2 = order_gale2.get("result")
            pnl = order_gale2.get("pnl")

            if result_gale2 == "WON":
                print("✅ Gale 2 venceu.")
                print("atualizando valores de ganho...")
                await api.update_win_value(USER_ID, pnl)
                print("atualizando ordem...")
                await api.update_trade_order_info(order_gale2.get("id"), USER_ID, "WON NA GALE 2")
                print("verificando valores de stop...")
                await api.verify_stop_values(USER_ID)
            else:
                print("❌ Gale 2 perdeu.")
                print("atualizando valores de perda...")
                await api.update_loss_value(USER_ID, gale2_valor)
                print("atualizando ordem...")
                await api.update_trade_order_info(order_gale2.get("id"), USER_ID, "LOST")
                print("verificando valores de stop...")
                await api.verify_stop_values(USER_ID)
            return

    print("❌ Todas as tentativas falharam.")
    print("atualizando valores de perda...")

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


        bot_options = await api.get_bot_options(USER_ID)
        valor_base = bot_options.get('entry_price')
        is_demo = bot_options.get('is_demo')

        print(f"Valor base: {valor_base}")
        print(f"Modo Demo: {is_demo}")

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


