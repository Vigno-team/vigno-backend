FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
RUN sed -i "s|http://deb.debian.org/debian$|${DEBIAN_MIRROR}|" /etc/apt/sources.list.d/debian.sources \
    && apt-get update --error-on=any -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends libpq5 libexpat1 \
    && rm -rf /var/lib/apt/lists/*
# Permite usar una cache de paquetes durante la construccion.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST
ARG PIP_DEFAULT_TIMEOUT=120
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
