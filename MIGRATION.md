# TraceOps AI Migration Notes

## v1 → v2 → v3 Upgrade Guide

All changes are backward-compatible. No API signature changes.
Drop-in replacement: overwrite the files listed below.

---

## Files Changed in v3

| File | Change |
|------|--------|
| `app/core/eas_config.py` | **NEW** — central config, import everywhere |
| `app/services/task_enforcement.py` | v3: confidence-based assignment, accuracy metric |
| `app/services/correlator.py` | v3: delayed queue, timeout fallback |
| `app/services/loop_detection.py` | v3: context classification, loop_type_context field |
| `app/services/scoring.py` | v3: rate-based AI efficiency, chain penalty, continuity |
| `app/services/deployment.py` | v3: L5 state-change verification, validation_depth_score |
| `app/services/anti_gaming.py` | v3: commit_quality_score (0–1), semantic diff |
| `app/api/metrics.py` | v3: adaptive tuning engine, POST /metrics/tune |
| `tests/test_v3.py` | **NEW** — full v3 test suite |
| `DEPLOYMENT.md` | **NEW** — free deployment guide |
| `render.yaml` | **NEW** — Render blueprint |
| `.github/workflows/test.yml` | **NEW** — GitHub Actions CI |

---

## Breaking Changes

**None.** All public function signatures are preserved.

New fields added to existing return types (additive, not breaking):
- `LoopResult.loop_type_context` — new field, defaults to `None`
- `LoopResult.loop_confidence` — was in v2, unchanged
- `ScoreBreakdown.details` — new keys added: `continuity_ratio`, `prompts_per_hour`, `outputs_per_hour`, `chain_penalty`
- `ValidationResult.validation_depth_score` — new field (same value as `.score`)
- `AntiGamingResult.commit_quality_score` — new field

---

## Config Migration

v1/v2 had hardcoded constants in each module. v3 centralizes all thresholds:

```python
# Old (v1/v2) — scattered hardcodes
SIMILARITY_THRESHOLD = 0.85
MIN_LOC_PER_COMMIT = 10

# New (v3) — all from eas_config
from app.core.eas_config import eas_config
eas_config.loop_detection.similarity_threshold_normal   # 0.85
eas_config.anti_gaming.min_loc_per_commit               # 10
```

Thresholds persist to `eas_config_state.json` when tuning engine runs.
Set `EAS_CONFIG_PATH` env var to change location.

---

## New Endpoints (v3)

```
POST /metrics/tune         — run adaptive tuning engine
GET  /metrics/tune/log     — view tuning history
GET  /metrics/config       — view current threshold config
```

---

## Database

No schema changes. All new fields are stored in existing `metadata` JSONB columns.

---

## Deployment

See `DEPLOYMENT.md` for full free-tier Render deployment (₹0/month).
Quick start: push to GitHub → connect Render → use `render.yaml` blueprint.
