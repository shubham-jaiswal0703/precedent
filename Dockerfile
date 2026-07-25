FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY precedent ./precedent
RUN pip install --no-cache-dir .

ENV PORT=8321
EXPOSE 8321
CMD ["sh", "-c", "uvicorn precedent.api.app:app --host 0.0.0.0 --port ${PORT}"]
