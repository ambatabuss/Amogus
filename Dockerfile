FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# إعلان المنفذ
EXPOSE 8080

# تمرير PORT عبر البيئة وتشغيل البوت
ENV PORT=8080
CMD ["sh", "-c", "python bot.py --port ${PORT}"]
