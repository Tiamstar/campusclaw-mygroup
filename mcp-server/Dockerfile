FROM python:3.12-slim
RUN pip install --no-cache-dir 'Flask>=3.1,<4' 'gunicorn>=26,<27' && useradd --create-home --uid 10001 appuser
WORKDIR /srv/mcp
COPY app.py ./app.py
USER appuser
EXPOSE 8090
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8090", "app:app"]
