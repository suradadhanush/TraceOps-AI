# EAS Free Deployment Guide — v3 Final

Total cost: ₹0/month. Stack: Render (API + Worker + PostgreSQL + Redis) + GitHub Actions CI.

---

## Architecture

```
GitHub repo
  └─ GitHub Actions      CI on every push
       └─ Render
            ├─ eas-api   FastAPI (free web service, 512MB)
            ├─ eas-worker Celery worker+beat combined (free)
            ├─ eas-db    PostgreSQL 16 (free, 1GB, 90-day TTL)
            └─ eas-redis Redis 7 (free, 25MB)

UptimeRobot → /health/deep every 14 min (prevents sleep, detects desync)
```

---

## Known Free-Tier Constraints & Mitigations

| Problem | Mitigation in v3 |
|---------|-----------------|
| API sleeps after 15 min | UptimeRobot pings /health/deep every 14 min |
| Worker restarts independently | /worker/health reports desync; manual trigger via POST /worker/scheduler/trigger |
| Filesystem ephemeral | Config stored in PostgreSQL (config_store table), not eas_config_state.json |
| Webhook drops on sleep | DB-first: payload stored before processing; /metrics/webhook/replay retries failed events |
| Redis 25MB limit | Only Celery queue uses Redis — lightweight usage, safe at this scale |
| PostgreSQL 90-day expiry | Reminder + dump procedure below |

---

## Step 1 — GitHub Setup

```bash
cd eas
git init
git add .
git commit -m "EAS v3 initial [EAS-bootstrap]"

# Create public repo at github.com/<you>/eas, then:
git remote add origin https://github.com/<you>/eas.git
git push -u origin main
```

Install commit hook:
```bash
python scripts/install_hook.py
```

---

## Step 2 — Render Setup

1. https://render.com → Sign up → Connect GitHub

**Option A: Blueprint (one-click)**
- Dashboard → New → Blueprint → select your repo
- Render reads `render.yaml` and creates all services automatically
- After creation, manually add these two secrets in each service's Environment tab:
  - `OPENAI_API_KEY` = `sk-...`
  - `ANTHROPIC_API_KEY` = `sk-ant-...`

**Option B: Manual (step by step)**

### 2a — PostgreSQL

Dashboard → New → PostgreSQL
```
Name:    eas-db
Plan:    Free
Region:  Singapore
```
Save the **Internal Database URL**.

### 2b — Redis

Dashboard → New → Redis
```
Name:    eas-redis
Plan:    Free
```
Save the **Internal Redis URL**.

### 2c — API Web Service

Dashboard → New → Web Service → Connect repo
```
Name:          eas-api
Runtime:       Python 3
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
Plan:          Free
Health Check:  /health
```

Environment variables:
```
DATABASE_URL          = postgresql+asyncpg://<internal-db-url-with-asyncpg>
SYNC_DATABASE_URL     = postgresql://<internal-db-url>
REDIS_URL             = <internal-redis-url>
CELERY_BROKER_URL     = <internal-redis-url>
CELERY_RESULT_BACKEND = <internal-redis-url>/1
SECRET_KEY            = <run: python -c "import secrets; print(secrets.token_hex(32))">
OPENAI_API_KEY        = sk-...
ANTHROPIC_API_KEY     = sk-ant-...
LLM_PROVIDER          = openai
LLM_MODEL             = gpt-4o-mini
APP_ENV               = production
LOG_LEVEL             = INFO
```

Note: For DATABASE_URL, replace `postgresql://` with `postgresql+asyncpg://`.

### 2d — Worker Service (Worker + Beat combined)

Dashboard → New → Web Service → same repo
```
Name:          eas-worker
Start Command: celery -A app.core.celery_app.celery_app worker --beat --loglevel=info --concurrency=2
Plan:          Free
```
Add identical environment variables as API.

---

## Step 3 — Initialize Database

After first deploy, open Render Shell on `eas-api`:
```bash
python -c "
import asyncio
from app.core.database import engine, Base
from app.models import models
from app.services.webhook_durability import WebhookEvent
from app.services.config_store import ConfigStore

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('All tables created.')

asyncio.run(init())
"
```

---

## Step 4 — Verify

```bash
# Health
curl https://eas-api.onrender.com/health
# → {"status":"ok","service":"eas","version":"3.0.0"}

# Deep health (DB + Redis + Worker)
curl https://eas-api.onrender.com/health/deep

# First task
curl -X POST https://eas-api.onrender.com/task/start \
  -H "Content-Type: application/json" \
  -d '{"goal": "Test EAS v3 deployment", "target_level": 3}'

# Metrics (requires key)
curl https://eas-api.onrender.com/metrics/ \
  -H "X-Metrics-Key: <your-SECRET_KEY>"

# Public metrics (no key)
curl https://eas-api.onrender.com/metrics/public
```

---

## Step 5 — GitHub Webhook (auto-ingest commits)

GitHub repo → Settings → Webhooks → Add webhook
```
Payload URL:  https://eas-api.onrender.com/event/github
Content type: application/json
Events:       Just the push event
```

---

## Step 6 — UptimeRobot (prevent sleep + detect desync)

1. https://uptimerobot.com → Free account
2. Add Monitor:
   ```
   Type:     HTTP(s)
   URL:      https://eas-api.onrender.com/health/deep
   Interval: 5 minutes
   ```
3. Add alert contact (email) — you'll get notified if DB or Redis goes down.

This also prevents the 15-min sleep. Two monitors = redundancy:
- Monitor 1: `/health` (basic liveness)
- Monitor 2: `/health/deep` (full stack check)

---

## Step 7 — GitHub Actions CI

The file `.github/workflows/test.yml` is already in the repo.
Tests run automatically on every push to `main`.

---

## Daily Usage Workflow

```bash
BASE=https://eas-api.onrender.com
KEY=<your-SECRET_KEY>

# Start of day
curl -X POST $BASE/task/start \
  -H "Content-Type: application/json" \
  -d '{"goal": "Build AnonCampus scoring service", "target_level": 5}'
# → save task_id

# Route AI through proxy (logs automatically)
curl -X POST $BASE/proxy/openai \
  -H "X-OpenAI-Key: sk-..." \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "payload": {"model": "gpt-4o-mini", "messages": [...]}}'

# Validate your deploy before claiming Level 5
curl -X POST $BASE/report/validate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://nsrit-esports-arena.onrender.com", "functional_path": "/health"}'

# End of day — close task
curl -X POST $BASE/task/end \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "final_level": 4}'

# Get markdown report
curl $BASE/report/daily/markdown

# Submit your honest judgment
curl -X POST $BASE/metrics/score/manual \
  -H "Content-Type: application/json" \
  -H "X-Metrics-Key: $KEY" \
  -d '{"date": "2025-05-04", "human_score": 68, "notes": "stuck on correlation for 2h"}'

# Check metrics
curl $BASE/metrics/ -H "X-Metrics-Key: $KEY"
```

---

## Recovering Failed Webhooks

If the API was asleep when GitHub pushed:
```bash
# Replay all failed/pending webhook events
curl -X POST $BASE/metrics/webhook/replay \
  -H "X-Metrics-Key: $KEY"

# Check status
curl $BASE/metrics/webhook/stats \
  -H "X-Metrics-Key: $KEY"
```

---

## Manual Scheduler Fallback

If Celery beat died:
```bash
# Trigger daily report manually
curl -X POST $BASE/worker/scheduler/trigger \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: $KEY" \
  -d '{"job": "daily_report"}'

# Check missed schedules
curl $BASE/worker/scheduler/missed \
  -H "X-Admin-Key: $KEY"
```

---

## PostgreSQL 90-Day Expiry Procedure

Before day 90 (set a calendar reminder):
```bash
# 1. Dump from Render external URL
pg_dump $EXTERNAL_DB_URL > eas_backup_$(date +%Y%m%d).sql

# 2. Create new free PostgreSQL on Render (same settings)
# 3. Restore
psql $NEW_EXTERNAL_DB_URL < eas_backup_$(date +%Y%m%d).sql

# 4. Update DATABASE_URL and SYNC_DATABASE_URL in both services
# 5. Redeploy both eas-api and eas-worker
```

---

## Cost Breakdown

| Component | Provider | Cost |
|-----------|----------|------|
| API (512MB, shared CPU) | Render Free | ₹0 |
| Celery Worker+Beat | Render Free | ₹0 |
| PostgreSQL 16 (1GB) | Render Free | ₹0 |
| Redis 7 (25MB) | Render Free | ₹0 |
| CI (2000 min/month) | GitHub Free | ₹0 |
| Uptime monitoring | UptimeRobot Free | ₹0 |
| LLM (gpt-4o-mini, daily) | OpenAI | ~₹150–400/month |
| **Total infra** | | **₹0** |

The only real cost is LLM analysis. Use `gpt-4o-mini` to keep it under ₹400/month.
If you want ₹0 LLM too: set `LLM_PROVIDER=anthropic` and use Claude's free API credits.

---

## Adaptive Tuning (after 2 days of real data)

After submitting ≥5 manual score comparisons:
```bash
curl -X POST $BASE/metrics/tune \
  -H "Content-Type: application/json" \
  -H "X-Metrics-Key: $KEY" \
  -d '{"force": false}'
```

View what changed:
```bash
curl $BASE/metrics/tune/log -H "X-Metrics-Key: $KEY"
```

Changes persist to the `eas_config_store` table in PostgreSQL. Container restarts won't lose them.
