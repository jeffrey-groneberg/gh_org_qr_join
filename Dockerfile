# Minimal single-stage image for the QR org-join app.
#
# NOTE: This Dockerfile is for LOCAL development / portability only. The Azure
# deployment (infra/) uses App Service's built-in Python runtime with an Oryx
# build (application_stack.python_version + SCM_DO_BUILD_DURING_DEPLOYMENT), so
# this image is NOT used by the Terraform deploy. To run it locally:
#   docker build -t qr-org-join . && docker run --rm -p 8000:8000 --env-file .env qr-org-join
FROM python:3.12-slim

# Don't write .pyc files; flush stdout/stderr immediately for live logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and templates.
COPY *.py ./
COPY templates ./templates

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# All configuration is provided via environment variables at run time
# (see .env.example). Example:
#   docker run --rm -p 8000:8000 --env-file .env qr-org-join
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 2 app:app"]
