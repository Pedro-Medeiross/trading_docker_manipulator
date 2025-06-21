FROM python:3.13.3-bullseye

COPY app /app

WORKDIR /app

RUN pip install -r requirements.txt
RUN pip install aiohttp

CMD ["python","-u","main.py"]