"""
EAS Threshold Configuration v3

Single source of truth for all tunable parameters.
All modules import from here. Adaptive tuning engine writes back here at runtime.
Never hardcode thresholds in business logic — always reference eas_config.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json
import os

# Config file path — tuning engine persists changes here
_CONFIG_PATH = os.environ.get("EAS_CONFIG_PATH", "eas_config_state.json")


@dataclass
class TaskEnforcementConfig:
    auto_assign_confidence_min: float = 0.75      # below this → mark unassigned
    auto_assign_window_minutes: int = 60           # search radius for nearest task
    hmac_max_age_seconds: int = 300               # reject replays older than this
    task_id_pattern: str = r'\[EAS-[a-f0-9\-]{8,}\]'  # commit message pattern


@dataclass
class CorrelatorConfig:
    weight_task_id: float = 0.60
    weight_time: float = 0.25
    weight_semantic: float = 0.15
    min_confidence: float = 0.25
    conflict_margin: float = 0.10                 # top-2 too close → ambiguous
    time_window_minutes: int = 30
    unresolved_timeout_hours: int = 2             # after this → assign lowest-conf cluster
    retry_on_new_event: bool = True


@dataclass
class LoopDetectionConfig:
    similarity_threshold_normal: float = 0.85
    similarity_threshold_debugging: float = 0.90
    similarity_threshold_research: float = 0.85
    drift_cancel_threshold: float = 0.25          # avg step drift above this → NOT loop
    min_occurrences: int = 3
    fuzzy_error_threshold: float = 0.90           # embedding sim for same-error clustering
    chain_no_output_minutes: int = 20             # >20 min AI chain with no output → penalty


@dataclass
class ScoringConfig:
    # Velocity
    idle_gap_minutes: int = 30
    velocity_fast_hours: int = 3
    velocity_med_hours: int = 6
    velocity_fast_bonus: int = 10
    velocity_med_bonus: int = 5
    # AI efficiency
    ai_efficiency_high: float = 0.30              # outputs/prompts → no penalty
    ai_efficiency_med: float = 0.10               # → mild penalty
    ai_efficiency_penalty_mild: int = 5
    ai_efficiency_penalty_strong: int = 10
    chain_no_output_minutes: int = 20             # >N min AI chain with no output → penalty
    ai_chain_penalty: int = 5                     # long chain with no output
    # Stability
    failed_deploy_penalty: int = 5
    repeated_error_penalty: int = 3
    max_stability_penalty: int = 30
    # Loop
    max_loop_penalty: int = 20
    loop_base_penalty: int = 5
    # Level 5 gate
    level5_requires_deploy: bool = True
    level5_deploy_min_level: int = 2
    level5_min_commit_loc: int = 10


@dataclass
class DeploymentConfig:
    health_path: str = "/health"
    default_timeout: float = 10.0
    # L5 state verification
    state_change_required_keys: list = field(default_factory=list)
    state_change_min_delta: float = 0.0


@dataclass
class AntiGamingConfig:
    min_loc_per_commit: int = 10
    commit_quality_min_score: float = 0.50        # below this → low quality
    ai_drop_threshold: float = 0.50              # AI usage dropped > 50% vs prior
    ai_suppression_output_max: int = 0           # max outputs when suppression flagged
    max_commits_per_hour: float = 20.0


@dataclass
class MetricsConfig:
    # Acceptance thresholds
    task_id_coverage_min_pct: float = 80.0
    correlation_accuracy_min_pct: float = 85.0
    score_deviation_max_points: float = 10.0
    loop_fp_rate_max: float = 0.30
    # Adaptive tuning
    tuning_max_change_pct: float = 0.10           # ±10% max weekly adjustment
    tuning_frequency_days: int = 7


@dataclass
class EASConfig:
    task_enforcement: TaskEnforcementConfig = field(default_factory=TaskEnforcementConfig)
    correlator: CorrelatorConfig = field(default_factory=CorrelatorConfig)
    loop_detection: LoopDetectionConfig = field(default_factory=LoopDetectionConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)
    anti_gaming: AntiGamingConfig = field(default_factory=AntiGamingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    # Tuning audit log
    _tuning_log: list = field(default_factory=list)

    def to_dict(self) -> dict:
        import dataclasses
        def _convert(obj):
            if dataclasses.is_dataclass(obj):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            return obj
        return _convert(self)

    def save(self, path: str = _CONFIG_PATH):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)

    @classmethod
    def load(cls, path: str = _CONFIG_PATH) -> "EASConfig":
        if not os.path.exists(path):
            return cls()
        try:
            with open(path) as f:
                data = json.load(f)
            cfg = cls()
            # Apply saved values
            for section_name, section_cls in [
                ("task_enforcement", TaskEnforcementConfig),
                ("correlator", CorrelatorConfig),
                ("loop_detection", LoopDetectionConfig),
                ("scoring", ScoringConfig),
                ("deployment", DeploymentConfig),
                ("anti_gaming", AntiGamingConfig),
                ("metrics", MetricsConfig),
            ]:
                if section_name in data:
                    saved = data[section_name]
                    section = getattr(cfg, section_name)
                    for k, v in saved.items():
                        if hasattr(section, k) and not k.startswith("_"):
                            setattr(section, k, v)
            cfg._tuning_log = data.get("_tuning_log", [])
            return cfg
        except Exception:
            return cls()


# Global singleton — import this everywhere
eas_config = EASConfig.load()
