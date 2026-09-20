FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY netarena_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN useradd --create-home --uid 10001 agent

# Copy only runtime inputs. Documentation and the digest-pinned Amber manifest
# cannot silently change the container that the manifest identifies.
COPY netarena_agent/__init__.py /app/netarena_agent/__init__.py
COPY netarena_agent/compiler.py /app/netarena_agent/compiler.py
COPY netarena_agent/server.py /app/netarena_agent/server.py

USER agent

EXPOSE 8001
ENTRYPOINT ["python", "-m", "netarena_agent.server", "--host", "0.0.0.0", "--port", "8001"]
