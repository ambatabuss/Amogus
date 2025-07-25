FROM python:3.11-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY protectioniv.py .

EXPOSE 8080

CMD ["python3", "protectioniv.py"]
