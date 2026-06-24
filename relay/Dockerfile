FROM python:3.13-slim

WORKDIR /app

COPY relay/requirements.txt relay/requirements.txt
RUN pip install --no-cache-dir -r relay/requirements.txt

COPY shared/ shared/
COPY relay/ relay/

EXPOSE 8000

CMD ["python", "-m", "relay.relay"]
