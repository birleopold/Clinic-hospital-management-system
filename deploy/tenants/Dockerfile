FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-core.txt requirements-tenant.txt ./
RUN pip install --no-cache-dir -r requirements-tenant.txt
COPY . .
RUN python manage.py collectstatic --noinput && useradd --uid 10001 --create-home clinic && mkdir -p /app/media && chown clinic:clinic /app/media
USER clinic
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
