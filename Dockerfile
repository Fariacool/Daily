FROM python:3.10-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm -rf /root/.cache
COPY *.py .
COPY *.toml .

EXPOSE 8080

CMD python -u tg_bot_daily.py
