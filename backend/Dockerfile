# Dockerfile - the recipe for the backend's container image.
# The SAME image is used in staging and prod; only environment variables differ.

# Start from a small official Python image.
FROM python:3.12-slim

# Don't write .pyc files, and show log output immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy ONLY the requirements first and install them. Docker caches each step,
# so if you change your code but not requirements.txt, this slow step is
# skipped on the next build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the application code.
COPY app ./app

# Security: don't run as the all-powerful "root" user inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Start the web server. 0.0.0.0 means "accept connections from outside the
# container", which is needed for Docker's port mapping to work.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
