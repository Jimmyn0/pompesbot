FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POMPESBOT_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# players.json et la base SQLite vivent dans le volume /data.
RUN useradd --create-home --uid 1000 bot && mkdir /data && chown bot /data
USER bot
VOLUME /data

CMD ["python", "main.py"]
