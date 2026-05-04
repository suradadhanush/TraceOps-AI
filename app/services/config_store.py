"""
Config Persistence Module (Fix 3)

Stores all EAS threshold config in PostgreSQL (table: eas_config_store).
Eliminates reliance on ephemeral container filesystem.

On startup: load from DB → apply to eas_config singleton.
On tuning: persist to DB via save_config_to_db().
Fallback: if DB unavailable → silently use in-memory defaults.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base, AsyncSessionLocal
from app.core.eas_config import EASConfig, eas_config

log = logging.getLogger("eas.config_store")


# ── ORM model ─────────────────────────────────────────────────────────────────

class ConfigStore(Base):
    __tablename__ = "eas_config_store"

    key        = Column(String(120), primary_key=True)
    value      = Column(Text, nullable=False)          # JSON blob
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


_CONFIG_KEY = "eas_global_config_v3"


# ── Persistence operations ────────────────────────────────────────────────────

async def save_config_to_db(cfg: Optional[EASConfig] = None) -> bool:
    """
    Persist the current eas_config (or supplied cfg) to PostgreSQL.
    Returns True on success, False on any DB error.
    """
    target = cfg or eas_config
    try:
        async with AsyncSessionLocal() as db:
            payload = json.dumps(target.to_dict(), default=str)
            result  = await db.execute(
                select(ConfigStore).where(ConfigStore.key == _CONFIG_KEY)
            )
            row = result.scalar_one_or_none()
            if row:
                row.value      = payload
                row.updated_at = datetime.utcnow()
            else:
                db.add(ConfigStore(key=_CONFIG_KEY, value=payload))
            await db.commit()
            log.info("eas_config persisted to DB")
            return True
    except Exception as exc:
        log.warning(f"Config DB persist failed (using in-memory): {exc}")
        return False


async def load_config_from_db() -> Optional[EASConfig]:
    """
    Load config from DB. Returns None if DB unavailable or no config stored.
    Caller should fall back to EASConfig() defaults on None.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConfigStore).where(ConfigStore.key == _CONFIG_KEY)
            )
            row = result.scalar_one_or_none()
            if not row:
                log.info("No stored config found in DB — using defaults")
                return None
            data = json.loads(row.value)
            cfg  = EASConfig()
            # Apply stored section values
            for section_name, section_cls_name in [
                ("task_enforcement", "TaskEnforcementConfig"),
                ("correlator",       "CorrelatorConfig"),
                ("loop_detection",   "LoopDetectionConfig"),
                ("scoring",          "ScoringConfig"),
                ("deployment",       "DeploymentConfig"),
                ("anti_gaming",      "AntiGamingConfig"),
                ("metrics",          "MetricsConfig"),
            ]:
                if section_name in data:
                    section = getattr(cfg, section_name)
                    for k, v in data[section_name].items():
                        if hasattr(section, k) and not k.startswith("_"):
                            setattr(section, k, v)
            cfg._tuning_log = data.get("_tuning_log", [])
            log.info("eas_config loaded from DB")
            return cfg
    except Exception as exc:
        log.warning(f"Config DB load failed (using defaults): {exc}")
        return None


async def apply_db_config_to_singleton() -> bool:
    """
    Called at startup: load from DB and apply to the live eas_config singleton.
    Returns True if DB config was applied, False if defaults are used.
    """
    loaded = await load_config_from_db()
    if loaded is None:
        return False
    # Mutate the singleton sections in-place (avoids breaking existing imports)
    global eas_config
    for attr in ("task_enforcement", "correlator", "loop_detection",
                 "scoring", "deployment", "anti_gaming", "metrics"):
        setattr(eas_config, attr, getattr(loaded, attr))
    eas_config._tuning_log = loaded._tuning_log
    return True
