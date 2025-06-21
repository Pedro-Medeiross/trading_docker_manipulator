import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def get_status_bot(user_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        async with session.get(f'http://69.62.92.8/bot-options/bot-options/{user_id}', headers=headers) as response:
            r = await response.json()
            status = r['status']
            return status
        

async def get_api_key(user_id: int):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        async with session.get(f'http://69.62.92.8/bot-options/api-key/{user_id}', headers=headers) as response:
            r = await response.json()
            api_key = r
            return api_key
        


async def update_status_bot(user_id: int, status: str):
    async with aiohttp.ClientSession() as session:
        auth = aiohttp.BasicAuth(os.getenv('API_USER'), os.getenv('API_PASS'))
        headers = {'Authorization': auth.encode()}
        data = {'status': status}
        async with session.put(f'http://69.62.92.8/bot-options/bot-options/{user_id}', json=data, headers=headers) as response:
            if response.status == 200:
                return True
            else:
                return False