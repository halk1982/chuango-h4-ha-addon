FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /app/requirements.txt
COPY h4 /app/h4
CMD ["python", "-m", "h4", "--options", "/data/options.json"]
