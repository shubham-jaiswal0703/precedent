FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY precedent ./precedent
RUN pip install --no-cache-dir ".[postgres]"

# The catalog, case packs, and speaker timelines are the library index; the
# media itself lives in VideoDB, so shipping these files is enough to deploy
# a working archive. (See HOSTING.md for moving this to Postgres.)
COPY data ./data

ENV PORT=8321
EXPOSE 8321
CMD ["sh", "-c", "uvicorn precedent.api.app:app --host 0.0.0.0 --port ${PORT}"]
