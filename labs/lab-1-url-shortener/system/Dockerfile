# One image for both the API and the worker; compose picks the command.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY shortener/pyproject.toml shortener/
COPY shortener/src shortener/src
ARG EXTRAS=aws
RUN pip install "./shortener[${EXTRAS}]"

RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "shortener.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
