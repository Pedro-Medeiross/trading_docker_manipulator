import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def get_status_bot(user_id: int, brokerage_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        async with session.get(f'https://api.multitradingob.com/bot-options/admin/{user_id}/{brokerage_id}', headers=headers) as response:
            r = await response.json()
            status = r['bot_status']
            return status
        

async def get_api_key(user_id: int, brokerage_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        async with session.get(f'https://api.multitradingob.com/user-brokerages/admin/{user_id}/{brokerage_id}', headers=headers) as response:
            r = await response.json()
            api_key = r
            return api_key
        

async def get_bot_options(user_id:int, brokerage_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        async with session.get(f'https://api.multitradingob.com/bot-options/admin/{user_id}/{brokerage_id}', headers=headers) as response:
            return await response.json()
        

async def update_status_bot(user_id: int, status: str, brokerage_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        data = {'bot_status': status}
        async with session.put(f'https://api.multitradingob.com/bot-options/admin/{user_id}/{brokerage_id}', json=data, headers=headers) as response:
            if response.status == 200:
                return True
            else:
                return False
            

async def reset_stop_values(user_id:int, brokerage_id: int):
    win_value = 0
    loss_value = 0

    async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
            headers = {'Authorization': auth.encode()}
            data = {'loss_value': loss_value, 'win_value': win_value}
            async with session.put(f'https://api.multitradingob.com/bot-options/admin/{user_id}/{brokerage_id}', json=data, headers=headers) as response:
                return await response.json()