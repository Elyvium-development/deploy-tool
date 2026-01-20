# Dockerfile
FROM python:3.11-slim

# Prevent python buffering so logs show instantly
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps:
# - git: for git fetch/pull
# - bash: for ./deploy.sh
# - ca-certificates: HTTPS git remotes
RUN apt-get update && apt-get install -y --no-install-recommends \
    git bash ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install --no-cache-dir fastapi uvicorn

# Copy only the script (rename if you want)
COPY deploy_ui.py /app/deploy_ui.py

EXPOSE 7070

# Run the app
CMD ["python", "/app/deploy_ui.py"]
