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


origins = ["http://localhost:3000", "http://127.0.0.1/8000", "http://localhost:8000", "http://localhost:3000",
           "https://api.multitradingob.com", "https://multitradingob.com", "https://www.multitradingob.com", "https://bot.multitradingob.com"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = docker.from_env()


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


# Verifica se a imagem docker já existe, senão constrói uma nova.
images = client.images.list()
if 'docker_bot:latest' not in [image.tags[0] for image in images]:
    print('Image not found, building new image, this may take a while...')
    print('Please wait...')
    client.images.build(path='.', dockerfile='./Dockerfile', tag='docker_bot:latest')
    print('Image built successfully')
else:
    print('Image found, skipping build')


@app.get("/start/{user_id}")
async def start_container(user_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)
    BROKERAGE_ID = 1
    get_api_key = await api.get_api_key(user_id, BROKERAGE_ID)
    TOKEN_TELEGRAN = os.environ.get("TOKEN_TELEGRAN")
    API_USER = os.environ.get("API_USER")
    API_PASS = os.environ.get("API_PASS")
    RABBITMQ_URL = os.environ.get('RABBITMQ_URL')
    bot_options = await api.get_bot_options(user_id)

    stop_loss = bot_options['stop_loss']
    stop_win = bot_options['stop_win']
    entry_price = bot_options['entry_price']

    api_key = get_api_key.get('api_key')
    print(f'API Key: {api_key}')

    print("Resetando stop values :")
    await api.reset_stop_values(user_id)

    if api_key is None:
        return {'message': 'api_key da corretora não cadastrada!'}
    
    if stop_loss or stop_win or entry_price == None:
        return {'message': 'Configurações base faltando'}
    
    decoded_api_key = base64.b64decode(api_key).decode('utf-8')
    
    containers = client.containers.list(all=True)

    env_vars = {
        'USER_ID': user_id,
        'API_TOKEN': decoded_api_key,
        'TOKEN_TELEGRAN': TOKEN_TELEGRAN,
        'API_USER': API_USER,
        'API_PASS': API_PASS,
        'BROKERAGE_ID': BROKERAGE_ID,
        'RABBITMQ_URL': RABBITMQ_URL
    }

    for container in containers:
        if container.name == f'bot_{user_id}':
            if container.status == 'running' and status_bot == 1:
                return {'message': 'App ja iniciado!'}
            if container.status == 'exited' and status_bot == 0 or container.status == 'exited' and status_bot == 2 or container.status == 'exited' and status_bot == 3:
                await api.update_status_bot(user_id, 1)
                container.start()
                return {'message': 'App iniciado!'}
            
    await api.update_status_bot(user_id, 1)
    client.containers.create(image='docker_bot:latest', name=f'bot_{user_id}', detach=True, environment=env_vars)
    client.containers.get(f'bot_{user_id}').start()
    return {'message': 'Bot created and started'}



@app.get("/stop/{user_id}")
async def stop_container(user_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)

    if status_bot == 0:
        return {'message': 'App ja parado!'}

    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == f'bot_{user_id}':
            if container.status == 'running':
                await api.update_status_bot(user_id, 0)
                container.kill()
                return {'message': 'App parado!'}
            elif container.status == 'exited':
                await api.update_status_bot(user_id, 0)
                return {'message': 'App ja parado!'}

    return {'message': 'Container not found'}



@app.get("/status/{user_id}")
async def status_container(user_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)

    if status_bot == 0:
        return {'message': 'App parado!'}

    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == f'bot_{user_id}':
            if container.status == 'running':
                return {'message': 'App rodando!'}
            elif container.status == 'exited':
                return {'message': 'App parado!'}

    return {'message': 'Container not found'}



@app.get("/stop_loss/{user_id}")
async def stop_loss_container(user_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)

    if status_bot == 0:
        return {'message': 'App ja parado!'}

    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == f'bot_{user_id}':
            if container.status == 'running':
                await api.update_status_bot(user_id, 3)
                container.kill()
                return {'message': 'Stop loss ativado!'}
            elif container.status == 'exited':
                await api.update_status_bot(user_id, 3)
                return {'message': 'Stop loss ativado!'}

    return {'message': 'Container not found'}


@app.get("/stop_win/{user_id}")
async def stop_win_container(user_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)

    if status_bot == 0:
        return {'message': 'App ja parado!'}

    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == f'bot_{user_id}':
            if container.status == 'running':
                await api.update_status_bot(user_id, 2)
                container.kill()
                return {'message': 'Stop win ativado!'}
            elif container.status == 'exited':
                await api.update_status_bot(user_id, 2)
                return {'message': 'Stop win ativado!'}

    return {'message': 'Container not found'}


@app.get("/restart/{user_id}")
async def restart_container(user_id: int, credentials: HTTPBasicCredentials = Depends(get_basic_credentials)):
    status_bot = await api.get_status_bot(user_id)

    if status_bot == 0:
        return {'message': 'App parado, iniciando novamente!'}

    containers = client.containers.list(all=True)

    for container in containers:
        if container.name == f'bot_{user_id}':
            if container.status == 'running':
                await api.update_status_bot(user_id, 1)
                container.restart()
                return {'message': 'App reiniciado!'}
            elif container.status == 'exited':
                await api.update_status_bot(user_id, 1)
                container.start()
                return {'message': 'App iniciado!'}

    return {'message': 'Container not found'}