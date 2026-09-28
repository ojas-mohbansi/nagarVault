FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 -r requirements.txt
COPY . .
EXPOSE 4004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4004"]
