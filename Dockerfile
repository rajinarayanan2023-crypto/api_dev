# Cloud Run runs whatever container this builds — no buildpack magic, so
# every runtime dependency has to be explicit here. Matches runtime.txt's
# pinned version (3.13 in .python-version is a local dev pyenv pin only,
# unrelated to what actually deploys).
FROM python:3.12-slim

# Cloud Run always injects PORT itself at container start — this default
# only matters for `docker run` locally without -e PORT=..., so local
# testing doesn't require guessing which port to curl.
ENV PORT=8080
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Split from the app code copy below so this (slow) layer only re-runs when
# requirements.txt actually changes, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run sends traffic to whatever port the container listens on, taken
# from its own PORT env var (set at deploy time, not necessarily 8080) —
# the shell form (not exec-array form) is what lets $PORT actually expand;
# the exec form would pass the literal string "$PORT" to uvicorn instead.
#
# Deliberately NOT running `alembic upgrade head` here (unlike the old
# Railway startCommand) — Cloud Run can start several instances of this
# same container concurrently (traffic spikes, rolling deploys), and
# migrations racing across instances is a real failure mode a single
# Railway instance never had to worry about. Run migrations as their own
# explicit step before deploying a new revision instead — see DEPLOY.md.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
