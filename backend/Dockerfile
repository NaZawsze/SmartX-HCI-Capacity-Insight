FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=10

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli docker-compose fonts-noto-cjk fontconfig \
    && find /usr/share/fonts/opentype/noto -type f ! -name 'NotoSerifCJK-Regular.ttc' -delete \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY VERSION ./VERSION
COPY RUNNER_VERSION ./RUNNER_VERSION
COPY backend/requirements*.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && find /usr/local/lib/python3.12/site-packages -type d \( -name __pycache__ -o -name tests -o -name test \) -prune -exec rm -rf '{}' + \
    && find /usr/local/lib/python3.12/site-packages -type d \( -name docs -o -name doc -o -name examples -o -name example \) -prune -exec rm -rf '{}' + \
    && find /usr/local/lib/python3.12/site-packages -type f -name '*.pyc' -delete \
    && (find /usr/local/lib/python3.12/site-packages -type f -name '*.so' -print0 | xargs -0 -r strip --strip-unneeded 2>/dev/null || true) \
    && rm -rf /root/.cache/pip

COPY backend/app ./app
RUN find ./app -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find ./app -type f -name '*.pyc' -delete

EXPOSE 8000

CMD ["uvicorn", "app.v2.main:app", "--host", "0.0.0.0", "--port", "8000"]
