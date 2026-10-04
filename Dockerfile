FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && printf 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main\n' > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-frontend.txt ./
RUN pip install --no-cache-dir 'pip>=26.2.1,<27' \
    && pip install --no-cache-dir -r requirements-frontend.txt \
    && useradd --create-home --uid 10001 library \
    && mkdir /backups && chown library:library /backups && chmod 0700 /backups
COPY --chown=library:library app ./app
COPY --chown=library:library frontend ./frontend
COPY --chown=library:library scripts ./scripts
COPY --chown=library:library alembic ./alembic
COPY --chown=library:library alembic.ini ./
USER library
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
