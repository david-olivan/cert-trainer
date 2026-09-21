FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=app:create_app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render inyecta PORT; en local se queda en 8000. docker-start.sh aplica
# las migraciones y siembra antes de ceder el proceso a gunicorn.
EXPOSE 8000
CMD ["sh", "docker-start.sh"]
