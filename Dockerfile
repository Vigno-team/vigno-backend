FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends libpq5 libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/staticfiles /app/data/cliente /app/data/ficticio /app/apps/ml/artifacts \
    && chown -R app:app /app/staticfiles /app/data /app/apps/ml/artifacts

FROM base AS production
COPY . .
USER app
EXPOSE 8000
CMD ["python", "deploy/backend.py"]

FROM base AS tareas
COPY requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt
COPY . .
USER app
CMD ["python", "deploy/tareas.py"]

# La etapa final conserva el comportamiento del Compose de desarrollo.
FROM base AS development
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
