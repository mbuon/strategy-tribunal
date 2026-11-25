"""Dedicated settings interface for the saved-settings layer (`.council/settings.json`).

Repo conventions: a typed config file plus CLI commands plus a Claude Code skill.
Every write validates the *effective* configuration (defaults < project < saved),
so an invalid value is refused and the file is left untouched. The CLI commands are
`council settings show|set|unset|reset|validate|routes|presets|wizard`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from .config import PRESETS, ROUTABLE_ROLES, CouncilConfig, EffectiveConfig, load_effective_config, parse_set_overrides

SAVED_FILE = ".council/settings.json"


class SettingsError(Exception):
    pass


def saved_path(root: Path) -> Path:
    return root / SAVED_FILE


def read_saved(root: Path) -> dict[str, Any]:
    p = saved_path(root)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise SettingsError(f"{p} must contain a JSON object")
    return data


def write_saved(root: Path, data: dict[str, Any]) -> Path:
    p = saved_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, p)
    return p


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _delete_path(d: dict, path: str) -> bool:
    parts = path.split(".")
    cur = d
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]
        return True
    return False


def _prune_empty(d: dict) -> dict:
    return {k: (_prune_empty(v) if isinstance(v, dict) else v) for k, v in d.items() if not (isinstance(v, dict) and not _prune_empty(v))}


def validate_candidate(root: Path, candidate: dict[str, Any]) -> EffectiveConfig:
    """Validate defaults < project < candidate saved settings. Raises SettingsError with the pydantic errors."""
    tmp_root = root
    # Reuse the loader by pointing it at a temporary saved file name.
    tmp_name = ".council/.settings.candidate.json"
    p = root / tmp_name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(candidate))
    try:
        return load_effective_config(tmp_root, saved_file=tmp_name)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        raise SettingsError(f"invalid settings: {msgs}") from e
    except ValueError as e:
        raise SettingsError(f"invalid settings: {e}") from e
    finally:
        try:
            p.unlink()
        except OSError:
            pass


def set_values(root: Path, items: list[str]) -> tuple[dict[str, Any], EffectiveConfig]:
    """Apply ``key=value`` items to the saved layer after validating the effective result."""
    overrides = parse_set_overrides(items)
    saved = read_saved(root)
    candidate = _deep_merge(saved, overrides)
    eff = validate_candidate(root, candidate)
    write_saved(root, candidate)
    return candidate, eff


def unset_values(root: Path, keys: list[str]) -> tuple[dict[str, Any], EffectiveConfig]:
    saved = read_saved(root)
    missing = [k for k in keys if not _delete_path(saved, k)]
    if missing:
        raise SettingsError(f"not present in saved settings: {missing}")
    saved = _prune_empty(saved)
    eff = validate_candidate(root, saved)
    write_saved(root, saved)
    return saved, eff


def reset(root: Path) -> bool:
    p = saved_path(root)
    if p.exists():
        p.unlink()
        return True
    return False


def routes_table(cfg: CouncilConfig) -> list[dict[str, str]]:
    rows = []
    for role in ROUTABLE_ROLES:
        rr = cfg.routing.for_role(role)
        provider = rr.provider or cfg.routing.default_provider
        note = ""
        if provider == "opencode" and not cfg.routing.opencode.enabled:
            note = "opencode disabled -> falls back to chat"
        rows.append({"role": role, "provider": provider, "model": rr.model or ("(opencode default: %s)" % cfg.routing.opencode.default_model if provider == "opencode" else "chat model"),
                     "sampling": "applied by provider" if rr.temperature is not None or rr.top_p is not None else "-", "note": note})
    return rows


def describe_presets() -> dict[str, dict[str, Any]]:
    return {name: body for name, body in PRESETS.items()}


# Wizard: a guided, non-interactive-safe sequence of questions answered through flags
WIZARD_FIELDS: list[tuple[str, str, str]] = [
    ("routing.default_provider", "Default provider for all roles (chat = this conversation)", "chat"),
    ("routing.opencode.enabled", "Enable the external OpenCode route by default (true/false)", "false"),
    ("routing.opencode.default_model", "OpenCode model (provider/model) used when a role has none", "claude-agent/haiku"),
    ("routing.roles.judge.provider", "Provider for the judge role (chat|opencode)", "chat"),
    ("judge.jury_size", "Number of judges per option (1-5)", "1"),
    ("judge.materiality_threshold", "Minimum meaningful score difference (0-5)", "0.5"),
    ("judge.promotion_margin", "Extra margin the challenger's lower bound must clear (0-5)", "0"),
    ("judge.unverified_gate_policy", "Treatment of unverified gates (fail|penalty|flag)", "penalty"),
    ("policy.weight_overrides", "Rubric weight overrides, JSON object {\"criterion name or crit_id\": weight > 0}; applied when the policy is registered, then normalised", "{}"),
    ("lenses.selection", "Lens selection (auto|explicit)", "auto"),
    ("lenses.max", "Maximum lenses per run (1-12)", "5"),
    ("review.panel_size", "Reviewers per round (0-6)", "2"),
    ("limits.min_rounds", "Minimum deliberation rounds", "2"),
    ("limits.max_rounds", "Maximum deliberation rounds", "4"),
    ("limits.stable_rounds_required", "Consecutive stable rounds that end a run", "2"),
    ("limits.max_model_calls", "Model-call budget per run", "60"),
    ("limits.max_tokens_estimate", "Token budget per run (measured on OpenCode, estimated on chat)", "400000"),
    ("limits.max_elapsed_seconds", "Wall-clock budget per run (seconds)", "1800"),
    ("limits.max_cost_usd", "Cost budget in USD (null when the provider reports no cost)", "null"),
]


def wizard_plan(current: CouncilConfig) -> list[dict[str, str]]:
    """Return the wizard questions with the current effective value for each key."""
    dump = current.model_dump(mode="json")
    rows = []
    for key, question, default in WIZARD_FIELDS:
        cur: Any = dump
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        rows.append({"key": key, "question": question, "default": default, "current": json.dumps(cur)})
    return rows


# One-line explanation per configuration key (dashboard, web UI, wizard). Keys with a wildcard role use <role>.
SETTINGS_DOCS: dict[str, str] = {
    "protocol_version": "Protocol version of the records this configuration is valid for (fixed).",
    "routing.default_provider": "Provider for every role without explicit routing: chat (this conversation), opencode (external, isolated sessions) or fixture (tests).",
    "routing.roles.<role>.provider": "Provider for one role (framer, policy_setter, strategist, reviewer, verifier, judge, challenger).",
    "routing.roles.<role>.model": "Model id for that role on the OpenCode route (provider/model as listed by `opencode models`).",
    "routing.roles.<role>.temperature": "Sampling temperature for providers that support it (the chat route cannot apply it).",
    "routing.roles.<role>.top_p": "Nucleus sampling for providers that support it (the chat route cannot apply it).",
    "routing.validation_fallbacks": "Models tried in order (one attempt each, via OpenCode, same payload and discussion) when a role's reply keeps failing validation after retries.max_attempts.",
    "routing.opencode.enabled": "Master switch for the external OpenCode route; off means the binary is never spawned.",
    "routing.opencode.binary": "Name or path of the OpenCode executable.",
    "routing.opencode.agent": "OpenCode agent used for every call (the shipped council-member agent denies all tools).",
    "routing.opencode.config_dir": "Folder with the agent's opencode.json; used as working directory and PWD for each call.",
    "routing.opencode.timeout_seconds": "Wall-clock limit per OpenCode call before it counts as failed.",
    "routing.opencode.retries": "Retries after a failed or timed-out OpenCode call before the fallback applies.",
    "routing.opencode.fallback": "After the retries: chat re-routes to the conversation model, fixture to the test provider, fail records a failed request.",
    "routing.opencode.default_model": "Model used by OpenCode-routed roles that name none.",
    "routing.opencode.model_fallbacks": "Requested model -> substitute when the requested id is not listed by OpenCode (recorded as a substitution).",
    "routing.opencode.verify_version": "Check `opencode --version` is v2.x once per run.",
    "routing.opencode.discover_models": "Run `opencode models` once per run and substitute unlisted ids.",
    "routing.opencode.standalone": "Run each call with a private OpenCode server so the restricted agent is found.",
    "judge.jury_size": "Judges per option version; disagreement widens the score bounds and is reported.",
    "judge.method": "Scoring method recorded on judgements (structured_scores; logprob_expectation has no backend).",
    "judge.half_widths.high": "Half-width of the conservative score interval at high judge confidence (heuristic).",
    "judge.half_widths.medium": "Half-width of the score interval at medium judge confidence (heuristic).",
    "judge.half_widths.low": "Half-width of the score interval at low judge confidence (heuristic).",
    "judge.half_width_label": "Label recorded with the bounds (documentation only).",
    "judge.promotion_margin": "Extra margin the challenger's lower bound must clear above the incumbent's upper bound.",
    "judge.materiality_threshold": "Minimum meaningful score difference; smaller gaps are ties and count towards stability.",
    "judge.unverified_gate_policy": "Unverified gate: fail disqualifies, penalty subtracts points, flag only reports.",
    "judge.unverified_gate_penalty": "Points subtracted per unverified gate under the penalty policy.",
    "judge.pairwise_tiebreak": "Close incumbent/challenger calls trigger two compare requests with swapped order.",
    "judge.screen_above": "Reserved for top-k pairwise screening; currently inert.",
    "judge.finalists": "Reserved for top-k pairwise screening; currently inert.",
    "judge.weight_perturbation": "Relative weight change used in the sensitivity analysis (ranking flips are reported).",
    "judge.rescore_scope": "Which versions are re-judged when evidence, rubric or judge configuration changes.",
    "policy.weight_overrides": "Rubric weights by criterion name or crit_ id that replace the policy setter's weights for score criteria.",
    "lenses.selection": "auto picks lenses from the brief; explicit uses lenses.explicit only.",
    "lenses.explicit": "Lens ids used when selection is explicit (or given with --lenses).",
    "lenses.min": "Minimum lenses per run under auto selection.",
    "lenses.max": "Maximum lenses per run under auto selection (one strategist call each per round).",
    "lenses.always_include_status_quo": "Accepted for symmetry; the status quo is always in the round-zero baseline (inert).",
    "lenses.always_include_staged": "Always include the staged-commitment lens under auto selection.",
    "lenses.always_include_information_option": "Always include the information-gathering lens under auto selection.",
    "review.panel_size": "Reviewers per round (0 disables review).",
    "review.challenge_cycles_max": "Reserved cap for challenge/response cycles per round; currently inert.",
    "limits.min_rounds": "Rounds that must complete before stability can stop the run.",
    "limits.max_rounds": "Hard cap on deliberation rounds.",
    "limits.stable_rounds_required": "Consecutive comparable rounds below materiality that count as stable.",
    "limits.max_model_calls": "Call budget per run, counted per request.",
    "limits.max_tokens_estimate": "Token budget: measured on OpenCode replies, estimated (chars/4) on chat replies; checked before each request.",
    "limits.max_elapsed_seconds": "Wall-clock budget since the run started.",
    "limits.max_cost_usd": "Cost budget; enforceable only when a provider reports cost.",
    "limits.finalisation_reserve_calls": "Calls kept back so the leader challenge and final judging can run.",
    "limits.max_reframes": "Reframes (new brief versions) accepted per run.",
    "limits.max_reopens": "Times an unresolved leader challenge may reopen deliberation.",
    "limits.max_verification_calls": "Verifier calls per run.",
    "limits.max_leader_challenges": "Dedicated sceptical passes against the leader (0 disables).",
    "storage.runs_root": "Folder (relative to the project root) that holds one sub-folder per run.",
    "storage.legacy_runs_root": "Older runs folder still searched when a run id is not found under runs_root.",
    "storage.dashboard": "Write <run>/index.html (the graphical dashboard) after every controller step.",
    "storage.ui_port": "Port of the local web UI (`council ui`), bound to 127.0.0.1 only.",
    "discussion.include": "What each role reads of the others' contributions: current_round_and_summaries (full text of this round, digests of earlier rounds), full, summaries or none.",
    "discussion.max_chars": "Cap on the discussion excerpt placed in each request (oldest material is shortened or dropped first).",
    "discussion.write_transcript": "Write every contribution to <run>/discussion/ and discussion.md.",
    "documents.max_file_bytes": "Largest single input file accepted by --docs.",
    "documents.max_total_bytes": "Total bytes accepted across all --docs files.",
    "documents.max_chars_in_payload": "Cap on document excerpts placed in each request.",
    "documents.max_chars_per_document": "Cap on the excerpt of one document in a request.",
    "documents.extensions": "File extensions read by --docs; others are skipped and listed in inputs/INDEX.md.",
    "defaults.preset": "Preset used when a run names none (standard, quick, deep, first_pass).",
    "defaults.chat_model": "Identity recorded for the conversation model when a run does not declare --chat-model.",
    "retries.max_attempts": "Attempts per request before the controller takes the failure transition.",
    "report.narrative_model_call": "Reserved flag for a model-written narrative; the report is controller-computed (inert).",
    "fixture_path": "Deterministic fixture file for autonomous test runs.",
    "seed": "Seed for the controller's own randomness (shuffles, counterbalanced order).",
}


PRESET_DOCS: dict[str, str] = {
    "standard": "project defaults: 2–4 rounds, up to 60 calls, 2 reviewers, 3 verifications, 1 leader challenge, 1 reopen; the full deliberation",
    "quick": "1–2 rounds, up to 24 calls, 1 reviewer, 1 verification, 2–3 lenses; demos and smoke tests (≈ 10–15 min on the chat route)",
    "deep": "3–6 rounds, up to 120 calls, 3 reviewers, 6 verifications, 2 reopens, jury of 2 judges, 4–6 lenses; high-stakes questions",
    "first_pass": "1 round, no review, no verification, no leader challenge: frame → policy → baseline → lenses → judge → report (the single-pass baseline)",
}


def allowed_values(key: str) -> str:
    """Human-readable type / allowed values / default for a key, read from the configuration schema."""
    from .config import CouncilConfig
    schema = CouncilConfig.model_json_schema()
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        if "$ref" in node:
            return resolve(defs[node["$ref"].split("/")[-1]])
        if "allOf" in node and len(node["allOf"]) == 1:
            return resolve(node["allOf"][0])
        return node

    node = schema
    parts = key.split(".")
    for i, part in enumerate(parts):
        node = resolve(node)
        props = node.get("properties", {})
        if part in props:
            node = props[part]
        elif node.get("additionalProperties"):
            node = node["additionalProperties"] if isinstance(node["additionalProperties"], dict) else {}
        else:
            return ""
    node = resolve(node)
    opts = node.get("anyOf")
    if opts:
        non_null = [resolve(o) for o in opts if o.get("type") != "null"]
        nullable = any(o.get("type") == "null" for o in opts)
        node = {**(non_null[0] if non_null else {}), "default": node.get("default")}
        if nullable:
            node["_nullable"] = True
    bits = []
    if node.get("enum"):
        bits.append("one of " + ", ".join(str(x) for x in node["enum"]))
    elif node.get("type"):
        t = node["type"]
        bits.append({"integer": "integer", "number": "number", "boolean": "true/false", "string": "text", "array": "list", "object": "JSON object"}.get(t, t))
    rng = []
    if "minimum" in node:
        rng.append(f"≥ {node['minimum']:g}")
    if "exclusiveMinimum" in node:
        rng.append(f"> {node['exclusiveMinimum']:g}")
    if "maximum" in node:
        rng.append(f"≤ {node['maximum']:g}")
    if rng:
        bits.append(" ".join(rng))
    if node.get("_nullable"):
        bits.append("or null")
    if "default" in node:
        bits.append(f"default {json.dumps(node['default'])}")
    return "; ".join(bits)


def describe(key: str) -> str:
    """Explanation for a concrete key such as ``routing.roles.judge.model`` or ``policy.weight_overrides.cost``."""
    if key in SETTINGS_DOCS:
        return SETTINGS_DOCS[key]
    parts = key.split(".")
    if len(parts) >= 4 and parts[0] == "routing" and parts[1] == "roles":
        return SETTINGS_DOCS.get(f"routing.roles.<role>.{parts[3]}", "")
    while len(parts) > 1:
        parts = parts[:-1]
        if ".".join(parts) in SETTINGS_DOCS:
            return SETTINGS_DOCS[".".join(parts)]
    return ""
