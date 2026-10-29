FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /srv/app
RUN useradd --system --uid 10001 --create-home appuser
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .
USER 10001:10001
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
