# Deploying RQ Lens

The production stack is `docker-compose.prod.yml`: Postgres, Redis, a one-off migration job, the API, the worker and the web app. It runs on any machine with Docker Compose v2, such as a small VPS (2 vCPU and 4 GB of RAM is enough for a demo).

Only the web app is published. The API, Postgres and Redis stay on the Compose network, and the web app forwards uploads, downloads and chat to the API with a short-lived signed token.

## 1. Configure

```sh
cp .env.prod.example .env.prod
openssl rand -base64 32   # run three times: POSTGRES_PASSWORD, API_JWT_SECRET, AUTH_SECRET
```

Fill in `.env.prod`:

- `PUBLIC_URL`: the address users open, for example `https://rq-lens.example.org`.
- The three secrets above.
- At least one sign-in provider. In the provider's console, set the callback URL to `<PUBLIC_URL>/api/auth/callback/google` (or `/github`).
- `LLM_API_KEY` and, if not using Gemini, `LLM_BASE_URL` and `LLM_MODEL`. Without a key the app still profiles data, runs SQL, gives rule-based verdicts for questions that already have a mapping (such as the sample project) and writes template insights. Chat and question parsing need a key.
- Optionally the per-user limits and `SENTRY_DSN`.

Variables exported in your shell override `.env.prod`. Unset any stale `AUTH_*` or `API_JWT_SECRET` values before starting.

## 2. Start

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml ps   # every service should become "healthy"
```

The `migrate` service runs `alembic upgrade head` and exits. The API and worker wait for it to finish successfully. Run the same command again after `git pull` to deploy a new version; migrations run first each time.

## 3. Put TLS in front

The web app listens on `WEB_PORT` (default 3000) over plain HTTP. Put a reverse proxy with TLS in front of it. With Caddy:

```
rq-lens.example.org {
    reverse_proxy localhost:3000
    request_body {
        max_size 500MB
    }
}
```

With nginx, set `client_max_body_size 500m;` and `proxy_read_timeout 300s;`. Chat answers stream over server-sent events, so also set `proxy_buffering off;` for `/api/`.

## Health checks

| Service | Check |
|---|---|
| API | `GET /health/live` (process up) and `GET /health/ready` (Postgres and Redis reachable; 503 otherwise). Compose uses `/health/ready`. |
| Worker | `arq --check api.worker.WorkerSettings` (the worker's heartbeat in Redis) |
| Web | `GET /` |
| Postgres, Redis | `pg_isready`, `redis-cli ping` |

An external uptime monitor should poll `<PUBLIC_URL>/`. The API is not published, so check its health from the host with `docker compose -f docker-compose.prod.yml exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read())"`.

## Error tracking

Set `SENTRY_DSN` in `.env.prod` to send unhandled API and worker errors to Sentry. The image installs `sentry-sdk` (the `sentry` extra), and `apps/api/observability.py` turns on the FastAPI and arq integrations. Request bodies, cookies and user details are not sent, because they can contain research data. `SENTRY_TRACES_SAMPLE_RATE` (0 to 1) turns on performance tracing.

Every AI call, including failed ones, is also logged in the `llm_calls` table, and every query in `queries`. The Usage page shows both per project.

## Backups

All state is in three named volumes:

- `pgdata`: users, projects, profiles, research questions, insights, traces.
- `appdata`: uploads and one DuckDB file per project.
- `redisdata`: the job queue only. It can be lost safely.

```sh
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U rqlens rqlens | gzip > rqlens-$(date +%F).sql.gz
docker run --rm -v rqscope_appdata:/data -v "$PWD":/backup alpine tar czf /backup/appdata-$(date +%F).tgz -C /data .
```

The volume name starts with the Compose project name, which defaults to the folder name (`rqscope` here). `docker volume ls` shows the exact name.

## Platforms without Compose

The API image (`apps/api/Dockerfile`, build with `--build-arg EXTRAS=sentry`) runs both the API (`uvicorn api.main:app --host 0.0.0.0 --port 8000`) and the worker (`arq api.worker.WorkerSettings`). Run `alembic upgrade head` as a release command. The web image is `apps/web/Dockerfile`. The API and worker must share the data directory (`DATA_DIR`), so on Railway or Fly.io run them on one machine with one volume, or give both the same mounted disk. Managed Postgres and Redis work; set `DATABASE_URL` (driver `postgresql+psycopg://`) and `REDIS_URL`.
