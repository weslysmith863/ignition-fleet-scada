# The mock CMMS as a container (ADR 0019). Build context is the repo root: docker compose build cmms
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY cmms/requirements.txt cmms/requirements.txt
RUN pip install --no-cache-dir -r cmms/requirements.txt

COPY cmms/ cmms/

# Run as an ordinary user, not root. The ticket file lives on a volume at /data; creating the folder here, owned by that user,
# makes a new volume start writable.
RUN useradd --system --uid 10002 cmms && mkdir /data && chown cmms /data
USER cmms

EXPOSE 8000

CMD ["uvicorn", "cmms.app:app", "--host", "0.0.0.0", "--port", "8000"]
