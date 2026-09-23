FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY campusclaw ./campusclaw
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/data/uploads && chown -R appuser:appuser /srv/data

USER appuser
ENV DATA_DIR=/srv/data
EXPOSE 8000
CMD ["sh", "-c", "flask --app campusclaw:create_app init-db && exec gunicorn -w 1 -b 0.0.0.0:8000 'campusclaw:create_app()'"]
