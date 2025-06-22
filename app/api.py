import aiohttp
import os
from dotenv import load_dotenv
from datetime import datetime
import pytz

load_dotenv()


async def get_bot_options(user_id):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        async with session.get(f'https://api.multitradingob.com/bot-options/bot-options/{user_id}', headers=headers) as response:
            return await response.json()
        

async def create_trade_order_info(user_id: int, order_id: str, symbol: str, order_type: str, quantity: float, price: float, status: str, brokerage_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        hora_brasilia = pytz.timezone('America/Sao_Paulo')
        hora_now = datetime.now(hora_brasilia)
        data = {
            'user_id': user_id,
            'order_id': order_id,
            'symbol': symbol,
            'order_type': order_type,
            'quantity': quantity,
            'price': price,
            'status': status,
            'date_time': hora_now.isoformat(),
            'brokerage_id': brokerage_id
        }
        async with session.post('https://api.multitradingob.com/trade-order-info/trade_order_info/create', json=data, headers=headers) as response:
            return await response.json()
        

async def update_trade_order_info(order_id, user_id,  status):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        data = {'user_id': user_id, 'order_id': order_id, 'status': status, }
        async with session.put(f'https://api.multitradingob.com/trade-order-info/trade_order_info/update', json=data, headers=headers) as response:
            return await response.json()


async def update_win_value(user_id, win_value):
    data = await get_bot_options(user_id)

    win_data_value = data['win_value']

    if win_data_value >= 0:
        win_data_value += win_value

        async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
            headers = {'Authorization': auth.encode()}
            data = {'win_value': win_data_value}
            async with session.put(f'https://api.multitradingob.com/bot-options/bot-options/{user_id}', json=data, headers=headers) as response:
                return await response.json()


async def update_loss_value(user_id, loss_value):
    data = await get_bot_options(user_id)

    loss_data_value = data['loss_value']

    if loss_data_value >= 0:
        loss_data_value += loss_value

        async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
            headers = {'Authorization': auth.encode()}
            data = {'loss_value': loss_data_value}
            async with session.put(f'https://api.multitradingob.com/bot-options/bot-options/{user_id}', json=data, headers=headers) as response:
                return await response.json()
        


async def verify_stop_values(user_id):
            data = await get_bot_options(user_id)

            stop_loss = data['stop_loss']
            stop_win = data['stop_win']
            win_value = data['win_value']
            loss_value = data['loss_value']

            if win_value >= stop_win:
                print(f"🛑 Stop Win atingido: {win_value} >= {stop_win}")
                async with aiohttp.ClientSession() as session:
                    auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
                    headers = {'Authorization': auth.encode()}
                    async with session.get(f'https://bot.multitradingob.com/stop_win/{user_id}', headers=headers) as response:
                        return await response.json()
            elif loss_value >= stop_loss:
                print(f"🛑 Stop Loss atingido: {loss_value} >= {stop_loss}")
                async with aiohttp.ClientSession() as session:
                    auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
                    headers = {'Authorization': auth.encode()}
                    async with session.get(f'hhttps://bot.multitradingob.com/stop_loss/{user_id}', headers=headers) as response:
                        return await response.json()
                    

async def reset_stop_values(user_id):
    win_value = 0
    loss_value = 0

    async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
            headers = {'Authorization': auth.encode()}
            data = {'loss_value': loss_value, 'win_value': win_value}
            async with session.put(f'https://api.multitradingob.com/bot-options/bot-options/{user_id}', json=data, headers=headers) as response:
                return await response.json()