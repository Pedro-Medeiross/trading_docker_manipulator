import os
import secrets
import docker
import api
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasicCredentials, HTTPBasic
from fastapi import Depends, HTTPException, status
from dotenv import load_dotenv
import base64

load_dotenv()

app = FastAPI()
security = HTTPBasic()

origins = [
    "http://localhost:3000", "http://127.0.0.1/8000", "http://localhost:8000", "http://localhost:3000",
    "https://api.multitradingob.com", "https://multitradingob.com", "https://www.multitradingob.com", "https://bot.multitradingob.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = docker.from_env()

BROKERAGE_CONFIGS = {
    1: {
        "image": "xofre_bot:latest",
        "dockerfile": "./Dockerfile.xofre",
        "build_path": "."
    },
}

def get_basic_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv('API_USER'))
    correct_password = secrets.compare_digest(credentials.password, os.getenv('API_PASS'))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.get("/start/{user_id}/{brokerage_id}")
async def start_container(user_id: int, brokerage_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    if brokerage_id not in BROKERAGE_CONFIGS:
        return {"message": "Corretora não suportada."}

    config = BROKERAGE_CONFIGS[brokerage_id]
    image_name = config["image"]

    images = client.images.list()
    if not any(image_name in tag for image in images for tag in image.tags):
        print(f'Image {image_name} not found, building...')
        client.images.build(path=config["build_path"], dockerfile=config["dockerfile"], tag=image_name)

    status_bot = await api.get_status_bot(user_id)
    get_api_key = await api.get_api_key(user_id, brokerage_id)
    bot_options = await api.get_bot_options(user_id)

    api_key = get_api_key.get('api_key')
    if not api_key:
        return {'message': 'api_key da corretora não cadastrada!'}

    if bot_options['stop_loss'] <= 0 or bot_options['stop_win'] <= 0 or bot_options['entry_price'] <= 0:
        return {'message': 'Configurações base faltando'}

    decoded_api_key = base64.b64decode(api_key).decode('utf-8')

    env_vars = {
        'USER_ID': user_id,
        'API_TOKEN': decoded_api_key,
        'TOKEN_TELEGRAN': os.environ.get("TOKEN_TELEGRAN"),
        'API_USER': os.environ.get("API_USER"),
        'API_PASS': os.environ.get("API_PASS"),
        'BROKERAGE_ID': brokerage_id,
        'RABBITMQ_URL': os.environ.get('RABBITMQ_URL'),
        'RABBITMQ_HOST': os.environ.get('RABBITMQ_HOST'),
        'RABBITMQ_USER': os.environ.get('RABBITMQ_USER'),
        'RABBITMQ_PASS': os.environ.get('RABBITMQ_PASS')
    }

    container_name = f"bot_{user_id}_{brokerage_id}"
    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == container_name:
            if container.status == 'running' and status_bot == 1:
                return {'message': 'App já iniciado!'}
            if container.status == 'exited':
                await api.update_status_bot(user_id, 1)
                container.start()
                return {'message': 'App iniciado!'}

    await api.update_status_bot(user_id, 1)
    client.containers.create(image=image_name, name=container_name, detach=True, environment=env_vars, network="trading_docker_manipulator_botnet")
    client.containers.get(container_name).start()
    return {'message': 'Bot created and started'}

@app.get("/stop/{user_id}/{brokerage_id}")
async def stop_container(user_id: int, brokerage_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)
    if status_bot == 0:
        return {'message': 'App já parado!'}

    container_name = f'bot_{user_id}_{brokerage_id}'
    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == container_name:
            await api.update_status_bot(user_id, 0)
            if container.status == 'running':
                container.kill()
                return {'message': 'App parado!'}
            return {'message': 'App já parado!'}

    return {'message': 'Container not found'}

@app.get("/status/{user_id}/{brokerage_id}")
async def status_container(user_id: int, brokerage_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    container_name = f'bot_{user_id}_{brokerage_id}'
    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == container_name:
            return {'message': 'App rodando!' if container.status == 'running' else 'App parado!'}

    return {'message': 'Container not found'}

@app.get("/stop_loss/{user_id}/{brokerage_id}")
async def stop_loss_container(user_id: int, brokerage_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)
    if status_bot == 0:
        return {'message': 'App já parado!'}

    container_name = f'bot_{user_id}_{brokerage_id}'
    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == container_name:
            await api.update_status_bot(user_id, 3)
            if container.status == 'running':
                container.kill()
            return {'message': 'Stop loss ativado!'}

    return {'message': 'Container not found'}

@app.get("/stop_win/{user_id}/{brokerage_id}")
async def stop_win_container(user_id: int, brokerage_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)
    if status_bot == 0:
        return {'message': 'App já parado!'}

    container_name = f'bot_{user_id}_{brokerage_id}'
    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == container_name:
            await api.update_status_bot(user_id, 2)
            if container.status == 'running':
                container.kill()
            return {'message': 'Stop win ativado!'}

    return {'message': 'Container not found'}

@app.get("/restart/{user_id}/{brokerage_id}")
async def restart_container(user_id: int, brokerage_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)

    container_name = f'bot_{user_id}_{brokerage_id}'
    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == container_name:
            await api.update_status_bot(user_id, 1)
            if container.status == 'running':
                container.restart()
                return {'message': 'App reiniciado!'}
            elif container.status == 'exited':
                container.start()
                return {'message': 'App iniciado!'}

    return {'message': 'Container not found'}
