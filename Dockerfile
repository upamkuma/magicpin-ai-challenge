FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY quality_gate.py .
COPY conversation_handlers.py .

EXPOSE 8080

CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8080"]
