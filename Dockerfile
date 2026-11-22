FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

VOLUME ["/app/data"]

ENTRYPOINT ["trends-monitor"]
CMD ["run", "--config", "/app/config.yaml"]
