"""Typed configuration contract with layered precedence and provenance.

Precedence (lowest -> highest):
  built-in defaults -> project ``council.config.json`` -> saved ``.council/settings.json``
  -> preset (named override layer) -> per-run overrides (CLI flags / --set).

``load_effective_config`` returns the validated ``CouncilConfig`` together with a
per-leaf provenance map so the effective configuration can be displayed with
the layer each value came from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import PROTOCOL_VERSION
from .ontology import Role, stable_hash

ProviderName = Literal["chat", "opencode", "fixture"]

ROUTABLE_ROLES = [
    Role.FRAMER.value,
    Role.POLICY_SETTER.value,
    Role.STRATEGIST.value,
    Role.REVIEWER.value,
    Role.VERIFIER.value,
    Role.JUDGE.value,
    Role.CHALLENGER.value,
]


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleRouting(_Cfg):
    provider: Optional[ProviderName] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class OpenCodeConfig(_Cfg):
    enabled: bool = False
    binary: str = "opencode"
    agent: str = "council-member"
    config_dir: str = "adapters/opencode"
    timeout_seconds: int = Field(default=300, ge=5, le=3600)
    retries: int = Field(default=1, ge=0, le=5)
    fallback: Literal["chat", "fixture", "fail"] = "chat"
    default_model: Optional[str] = None
    model_fallbacks: dict[str, str] = {}
    verify_version: bool = True
    discover_models: bool = True
    # Run each call with a private server (``--standalone``). Verified: the background
    # service resolves project config from the enclosing project root and does not see the
    # restricted agent defined in ``config_dir``; standalone mode loads it from the working directory.
    standalone: bool = True


class Routing(_Cfg):
    default_provider: ProviderName = "chat"
    roles: dict[str, RoleRouting] = {}
    opencode: OpenCodeConfig = OpenCodeConfig()
    # Models tried, in order, when a role's reply keeps failing validation on its own route (schema errors, unknown ids)
    # after retries.max_attempts: each gets one attempt through OpenCode with the same payload (discussion included) and
    # the previous error. "fixture" is accepted for tests.
    validation_fallbacks: list[str] = []

    @field_validator("validation_fallbacks")
    @classmethod
    def _fallback_ids(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x != "fixture" and "/" not in x]
        if bad:
            raise ValueError(f"routing.validation_fallbacks entries must be provider/model ids (or 'fixture'): {bad}")
        return v

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: dict[str, RoleRouting]) -> dict[str, RoleRouting]:
        unknown = set(v) - set(ROUTABLE_ROLES)
        if unknown:
            raise ValueError(f"unknown roles in routing.roles: {sorted(unknown)}; allowed: {ROUTABLE_ROLES}")
        return v

    def for_role(self, role: str) -> RoleRouting:
        rr = self.roles.get(role, RoleRouting())
        provider = rr.provider or self.default_provider
        return RoleRouting(provider=provider, model=rr.model, temperature=rr.temperature, top_p=rr.top_p)


class HalfWidths(_Cfg):
    high: float = Field(default=0.5, ge=0.0, le=5.0)
    medium: float = Field(default=1.0, ge=0.0, le=5.0)
    low: float = Field(default=1.5, ge=0.0, le=5.0)


class JudgeConfig(_Cfg):
    jury_size: int = Field(default=1, ge=1, le=5)
    method: Literal["structured_scores", "logprob_expectation"] = "structured_scores"
    half_widths: HalfWidths = HalfWidths()
    half_width_label: str = "heuristic"
    promotion_margin: float = Field(default=0.0, ge=0.0, le=5.0)
    materiality_threshold: float = Field(default=0.5, ge=0.0, le=5.0)
    unverified_gate_policy: Literal["fail", "penalty", "flag"] = "penalty"
    unverified_gate_penalty: float = Field(default=1.0, ge=0.0, le=10.0)
    pairwise_tiebreak: bool = True
    screen_above: int = Field(default=6, ge=2, le=50)
    finalists: int = Field(default=3, ge=2, le=10)
    weight_perturbation: float = Field(default=0.2, ge=0.0, le=1.0)
    rescore_scope: Literal["all_active", "incumbent_and_new"] = "all_active"


class LensConfig(_Cfg):
    selection: Literal["auto", "explicit"] = "auto"
    explicit: list[str] = []
    min: int = Field(default=3, ge=1, le=12)
    max: int = Field(default=5, ge=1, le=12)
    always_include_status_quo: bool = True
    always_include_staged: bool = True
    always_include_information_option: bool = True

    @model_validator(mode="after")
    def _min_le_max(self) -> "LensConfig":
        if self.min > self.max:
            raise ValueError("lenses.min must be <= lenses.max")
        return self


class ReviewConfig(_Cfg):
    panel_size: int = Field(default=2, ge=0, le=6)
    challenge_cycles_max: int = Field(default=1, ge=0, le=3)


class Limits(_Cfg):
    min_rounds: int = Field(default=2, ge=0, le=20)
    max_rounds: int = Field(default=4, ge=1, le=20)
    stable_rounds_required: int = Field(default=2, ge=1, le=10)
    max_model_calls: int = Field(default=60, ge=1, le=10000)
    max_tokens_estimate: int = Field(default=400_000, ge=1000)
    max_elapsed_seconds: float = Field(default=1800.0, gt=0)
    max_cost_usd: Optional[float] = Field(default=None, ge=0.0)
    finalisation_reserve_calls: int = Field(default=3, ge=0, le=50)
    max_reframes: int = Field(default=1, ge=0, le=5)
    max_reopens: int = Field(default=1, ge=0, le=5)
    max_verification_calls: int = Field(default=3, ge=0, le=50)
    max_leader_challenges: int = Field(default=1, ge=0, le=5)

    @model_validator(mode="after")
    def _rounds(self) -> "Limits":
        if self.min_rounds > self.max_rounds:
            raise ValueError("limits.min_rounds must be <= limits.max_rounds")
        if self.finalisation_reserve_calls >= self.max_model_calls:
            raise ValueError("limits.finalisation_reserve_calls must be < limits.max_model_calls")
        return self


class PolicyConfig(_Cfg):
    """Rubric settings applied when the evaluation policy is registered (phase 2).

    ``weight_overrides`` maps a criterion id (``crit_cost``) or a criterion name (matched case-insensitively
    after slugging, e.g. ``"Cost efficiency"``) to the relative weight the controller assigns to that score
    criterion instead of the weight proposed by the policy setter. Weights are normalised afterwards as usual.
    Keys that match no criterion in a run are recorded as unapplied."""

    weight_overrides: dict[str, float] = {}

    @field_validator("weight_overrides")
    @classmethod
    def _positive(cls, v: dict[str, float]) -> dict[str, float]:
        bad = {k: w for k, w in v.items() if not (w > 0)}
        if bad:
            raise ValueError(f"policy.weight_overrides values must be > 0: {bad}")
        return v


class StorageConfig(_Cfg):
    """Where runs are stored. ``runs_root`` is relative to the project root (the folder Claude Code is started in);
    each run gets its own folder named ``YYYY-MM-DD_HH-MM-SS_question-slug`` holding every file of that
    deliberation. ``legacy_runs_root`` is still searched when a run id is not found under ``runs_root``."""

    runs_root: str = "council_outcomes"
    legacy_runs_root: str = ".council/runs"
    dashboard: bool = True          # write <run>/index.html after every controller step
    ui_port: int = Field(default=8771, ge=1024, le=65535)   # preferred port; a port held by another program is skipped


class DiscussionConfig(_Cfg):
    """What each role reads of the other roles' contributions (the discussion transcript)."""

    include: Literal["current_round_and_summaries", "full", "summaries", "none"] = "current_round_and_summaries"
    max_chars: int = Field(default=30_000, ge=1000, le=2_000_000)
    write_transcript: bool = True


class DocumentsConfig(_Cfg):
    """Limits for user-supplied files and folders (--docs)."""

    max_file_bytes: int = Field(default=200_000, ge=1000)
    max_total_bytes: int = Field(default=2_000_000, ge=1000)
    max_chars_in_payload: int = Field(default=40_000, ge=500)
    max_chars_per_document: int = Field(default=12_000, ge=200)
    extensions: list[str] = [".md", ".txt", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".sql", ".log"]


class DefaultsConfig(_Cfg):
    """What a run uses when the command line says nothing: the preset and the identity recorded for the chat model."""

    preset: Optional[Literal["standard", "quick", "deep", "first_pass"]] = None
    chat_model: Optional[str] = None


class Retries(_Cfg):
    max_attempts: int = Field(default=2, ge=1, le=5)


class ReportConfig(_Cfg):
    narrative_model_call: bool = False


class CouncilConfig(_Cfg):
    protocol_version: str = PROTOCOL_VERSION
    routing: Routing = Routing()
    judge: JudgeConfig = JudgeConfig()
    lenses: LensConfig = LensConfig()
    review: ReviewConfig = ReviewConfig()
    limits: Limits = Limits()
    policy: PolicyConfig = PolicyConfig()
    storage: StorageConfig = StorageConfig()
    discussion: DiscussionConfig = DiscussionConfig()
    documents: DocumentsConfig = DocumentsConfig()
    defaults: DefaultsConfig = DefaultsConfig()
    retries: Retries = Retries()
    report: ReportConfig = ReportConfig()
    fixture_path: Optional[str] = None
    seed: int = 7

    @field_validator("protocol_version")
    @classmethod
    def _v(cls, v: str) -> str:
        if v != PROTOCOL_VERSION:
            raise ValueError(f"config protocol_version {v!r} != {PROTOCOL_VERSION!r}")
        return v

    def judge_config_hash(self) -> str:
        return stable_hash(self.judge.model_dump())


PRESETS: dict[str, dict[str, Any]] = {
    "standard": {},
    "quick": {
        "limits": {"min_rounds": 1, "max_rounds": 2, "stable_rounds_required": 1, "max_model_calls": 24,
                   "finalisation_reserve_calls": 2, "max_verification_calls": 1},
        "review": {"panel_size": 1},
        "lenses": {"min": 2, "max": 3},
    },
    "deep": {
        "limits": {"min_rounds": 3, "max_rounds": 6, "max_model_calls": 120, "max_verification_calls": 6,
                   "max_reopens": 2},
        "review": {"panel_size": 3},
        "judge": {"jury_size": 2},
        "lenses": {"min": 4, "max": 6},
    },
    # First-pass workflow (llm-council style): frame -> policy -> generate -> judge -> report.
    "first_pass": {
        "limits": {"min_rounds": 1, "max_rounds": 1, "stable_rounds_required": 1, "max_leader_challenges": 0,
                   "max_verification_calls": 0},
        "review": {"panel_size": 0, "challenge_cycles_max": 0},
    },
}


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, overlay: dict, prov: dict[str, str], layer: str, path: str = "") -> dict:
    out = dict(base)
    for k, v in overlay.items():
        p = f"{path}.{k}" if path else k
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v, prov, layer, p)
        else:
            out[k] = v
            _mark(prov, p, v, layer)
    return out


def _mark(prov: dict[str, str], path: str, value: Any, layer: str) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _mark(prov, f"{path}.{k}", v, layer)
    else:
        prov[path] = layer


def _leaf_paths(d: dict, path: str = "") -> list[str]:
    out: list[str] = []
    for k, v in d.items():
        p = f"{path}.{k}" if path else k
        if isinstance(v, dict) and v:
            out.extend(_leaf_paths(v, p))
        else:
            out.append(p)
    return out


def parse_set_overrides(items: list[str]) -> dict[str, Any]:
    """Parse ``--set a.b.c=value`` items. Values are parsed as JSON when possible."""
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set expects key=value, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        cur = out
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value
    return out


class EffectiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: CouncilConfig
    provenance: dict[str, str]
    layers_present: dict[str, bool]
    preset: Optional[str] = None

    def enforcement_table(self) -> list[dict[str, str]]:
        c = self.config.limits
        oc = self.config.routing.opencode
        cost_mode = "measured when provider reports cost; otherwise unavailable and not enforceable"
        return [
            {"limit": "max_model_calls", "value": str(c.max_model_calls), "enforcement": "counted (measured) per request; finalisation reserve kept"},
            {"limit": "max_tokens_estimate", "value": str(c.max_tokens_estimate), "enforcement": "measured on OpenCode replies; estimated (len/4) on chat replies"},
            {"limit": "max_elapsed_seconds", "value": str(c.max_elapsed_seconds), "enforcement": "measured wall clock since run start"},
            {"limit": "max_cost_usd", "value": str(c.max_cost_usd), "enforcement": cost_mode},
            {"limit": "max_rounds / min_rounds", "value": f"{c.max_rounds} / {c.min_rounds}", "enforcement": "counted"},
            {"limit": "external routes", "value": "opencode enabled" if oc.enabled else "none", "enforcement": "opt-in only; binary never spawned when disabled"},
        ]


def load_effective_config(
    root: Path,
    *,
    preset: Optional[str] = None,
    overrides: Optional[dict[str, Any]] = None,
    project_file: str = "council.config.json",
    saved_file: str = ".council/settings.json",
) -> EffectiveConfig:
    prov: dict[str, str] = {}
    defaults = CouncilConfig().model_dump(mode="json")
    for p in _leaf_paths(defaults):
        prov[p] = "defaults"
    merged = defaults
    layers_present = {"defaults": True, "project": False, "saved": False, "preset": False, "override": False}

    project_path = root / project_file
    if project_path.exists():
        merged = _deep_merge(merged, _read_json(project_path), prov, "project")
        layers_present["project"] = True

    saved_path = root / saved_file
    if saved_path.exists():
        merged = _deep_merge(merged, _read_json(saved_path), prov, "saved")
        layers_present["saved"] = True

    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}; available: {sorted(PRESETS)}")
        merged = _deep_merge(merged, PRESETS[preset], prov, f"preset:{preset}")
        layers_present["preset"] = True

    if overrides:
        merged = _deep_merge(merged, overrides, prov, "override")
        layers_present["override"] = True

    cfg = CouncilConfig.model_validate(merged)
    return EffectiveConfig(config=cfg, provenance=prov, layers_present=layers_present, preset=preset)


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data
