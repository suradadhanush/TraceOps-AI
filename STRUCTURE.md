# TraceOps AI — Folder Structure

```
TraceOps-AI/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── tasks.py          # Task lifecycle endpoints
│   │   ├── events.py         # Event ingestion endpoints
│   │   ├── reports.py        # Report endpoints
│   │   └── proxy.py          # AI proxy endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py         # Environment config
│   │   ├── database.py       # DB session management
│   │   └── celery_app.py     # Celery setup
│   ├── models/
│   │   ├── __init__.py
│   │   └── models.py         # SQLAlchemy ORM models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── scoring.py        # Deterministic scoring engine
│   │   ├── loop_detection.py # Loop/repetition detection
│   │   ├── deployment.py     # Deployment validator
│   │   ├── llm_analyzer.py   # LLM bottleneck analysis
│   │   ├── normalizer.py     # Event normalizer
│   │   ├── correlator.py     # Correlation engine
│   │   └── report_gen.py     # Report generator
│   ├── tasks/
│   │   ├── __init__.py
│   │   └── celery_tasks.py   # Celery async tasks
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── alembic/
│   ├── env.py
│   └── versions/
├── scripts/
│   └── seed.py
├── tests/
│   ├── test_scoring.py
│   └── test_loop_detection.py
├── main.py
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── n8n_workflow.json
```
