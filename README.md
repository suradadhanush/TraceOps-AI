# Execution Audit System (EAS)

Production-grade developer execution tracker. Aggregates AI usage, Git events, and deploy logs into a scored daily audit.

---

## Quick Start

### 1. Clone & configure

```bash
git clone <your-repo>/eas
cd eas
cp .env.example .env
# Edit .env: add OPENAI_API_KEY and/or ANTHROPIC_API_KEY
```

### 2. Start with Docker Compose

```bash
docker compose up --build
```

Services:
- API → http://localhost:8000
- Docs → http://localhost:8000/docs
- PostgreSQL → localhost:5432
- Redis → localhost:6379
- Celery worker + beat scheduler (automatic)

### 3. Manual setup (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL and Redis, then:
uvicorn main:app --reload --port 8000

# In separate terminals:
celery -A app.core.celery_app.celery_app worker --loglevel=info
celery -A app.core.celery_app.celery_app beat --loglevel=info
```

---

## Architecture

```
[AI Proxy] ─┐
            ├──> [Event Ingestion] ──> [Normalizer] ──> [Correlator]
[GitHub]  ──┤                                              │
[Deploy]  ──┘                                         [Scoring Engine]
                                                           │
                                                    [Loop Detection]
                                                           │
                                                     [LLM Analyzer]
                                                           │
                                                    [Report Generator]
```

### Scoring Formula
```
Score = (level × 10) + velocity - stability_penalty - ai_penalty

velocity:
  < 3h  → +10
  3–6h  → +5
  > 6h  → 0

stability_penalty:
  per failed deploy    → -5
  per repeated error   → -3
  (capped at 30)

ai_penalty:
  loop detected        → -5 to -15 (based on severity)
  per unproductive AI  → -2
  (capped at 20)
```

---

## API Reference

### Task Lifecycle

#### Start a task
```bash
curl -X POST http://localhost:8000/task/start \
  -H "Content-Type: application/json" \
  -d '{"goal": "Fix login bug in auth service", "target_level": 4}'
```

Response:
```json
{
  "task_id": "abc123-...",
  "goal": "Fix login bug in auth service",
  "target_level": 4,
  "started_at": "2025-05-03T10:00:00",
  "status": "active",
  "instructions": "Add [EAS-abc123-...] to your git commits."
}
```

#### End a task
```bash
curl -X POST http://localhost:8000/task/end \
  -H "Content-Type: application/json" \
  -d '{"task_id": "abc123-...", "final_level": 3}'
```

Response includes score breakdown and loop detection results.

---

### Event Ingestion

#### Ingest a generic event
```bash
curl -X POST http://localhost:8000/event/ \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "abc123-...",
    "event_type": "error",
    "source": "backend",
    "metadata": {"message": "KeyError: user_id in views.py"}
  }'
```

#### GitHub webhook
Configure your repo: `Settings → Webhooks → http://localhost:8000/event/github`

#### Deploy event (Render/Vercel/CI)
```bash
curl -X POST "http://localhost:8000/event/deploy?task_id=abc123-..." \
  -H "Content-Type: application/json" \
  -d '{"status": "failed", "platform": "render", "service": "eas-api", "url": "https://myapp.onrender.com"}'
```

---

### AI Proxy

Route your AI calls through EAS instead of directly to OpenAI/Anthropic.

#### OpenAI via proxy
```bash
curl -X POST http://localhost:8000/proxy/openai \
  -H "Content-Type: application/json" \
  -H "X-OpenAI-Key: sk-..." \
  -d '{
    "task_id": "abc123-...",
    "payload": {
      "model": "gpt-4o",
      "messages": [{"role": "user", "content": "How do I fix a JWT expiry bug?"}]
    }
  }'
```

#### Anthropic via proxy
```bash
curl -X POST http://localhost:8000/proxy/anthropic \
  -H "Content-Type: application/json" \
  -H "X-Anthropic-Key: sk-ant-..." \
  -d '{
    "task_id": "abc123-...",
    "payload": {
      "model": "claude-sonnet-4-20250514",
      "max_tokens": 1000,
      "messages": [{"role": "user", "content": "Debug this FastAPI 422 error"}]
    }
  }'
```

---

### Reports

#### Get today's report (JSON)
```bash
curl http://localhost:8000/report/daily
```

#### Get today's report (Markdown)
```bash
curl http://localhost:8000/report/daily/markdown
```

#### Force regenerate
```bash
curl -X POST http://localhost:8000/report/generate
```

#### Validate a deployment
```bash
curl -X POST http://localhost:8000/report/validate \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://nsrit-esports-arena.onrender.com",
    "functional_path": "/api/health",
    "functional_expected_status": 200,
    "functional_expected_keys": ["status"]
  }'
```

---

### Daily Workflow

**Start of day:**
```bash
# Create task for each goal
curl -X POST http://localhost:8000/task/start \
  -d '{"goal": "Build AnonCampus scoring service", "target_level": 5}'
```

**During the day:**
- Commit with `[EAS-<task_id>]` in message
- Route AI calls through proxy
- Let Celery auto-fetch GitHub commits every 30 min

**End of day:**
```bash
# Close each task
curl -X POST http://localhost:8000/task/end \
  -d '{"task_id": "<id>", "final_level": 4}'

# Generate report
curl -X POST http://localhost:8000/report/generate

# Read markdown audit
curl http://localhost:8000/report/daily/markdown
```

---

## n8n Workflow

Import `n8n_workflow.json` into your n8n instance.

Set environment variables in n8n:
- `EAS_API_URL` = `http://your-eas-host:8000`
- `GITHUB_REPO` = `owner/repo`
- `DEPLOY_LOGS_URL` = your deploy logs API

The workflow runs daily at 10 PM, fetches all data, triggers scoring, runs LLM analysis, and formats the report.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Git Commit Convention

Add `[EAS-<task_id>]` anywhere in your commit message:

```
feat: implement JWT refresh [EAS-abc123-...]
fix: resolve loop in auth middleware [EAS-abc123-...]
```

EAS auto-correlates the commit to the task.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | — | Async PostgreSQL URL |
| `REDIS_URL` | ✅ | — | Redis URL |
| `OPENAI_API_KEY` | ⚠️ | — | Required if LLM_PROVIDER=openai |
| `ANTHROPIC_API_KEY` | ⚠️ | — | Required if LLM_PROVIDER=anthropic |
| `LLM_PROVIDER` | — | `openai` | `openai` or `anthropic` |
| `EMBEDDING_SIMILARITY_THRESHOLD` | — | `0.85` | Loop detection sensitivity |
| `LOOP_MIN_OCCURRENCES` | — | `3` | Minimum repeats to flag loop |
| `VELOCITY_FAST_THRESHOLD_HOURS` | — | `3` | Hours for max velocity bonus |
| `VELOCITY_MED_THRESHOLD_HOURS` | — | `6` | Hours for medium velocity bonus |
