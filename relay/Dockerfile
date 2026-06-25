FROM python:3.13-slim

WORKDIR /app

COPY relay/requirements.txt relay/requirements.txt
RUN pip install --no-cache-dir -r relay/requirements.txt

COPY shared/ shared/
COPY relay/ relay/

ARG GIT_VERSION=""
ARG GIT_MESSAGE=""
ENV GIT_VERSION=${GIT_VERSION}
ENV GIT_MESSAGE=${GIT_MESSAGE}

EXPOSE 8000

CMD ["python", "-m", "relay.relay"]
