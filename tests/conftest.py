from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))

from build_fixtures import LENSES, QUESTION, write_all  # noqa: E402

from llm_council.config import load_effective_config  # noqa: E402
from llm_council.engine import Engine  # noqa: E402
from llm_council.providers import build_providers, drive_until_chat_or_terminal  # noqa: E402
from llm_council.providers.fixture import FixtureProvider  # noqa: E402
from llm_council.state import Store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _regenerate_fixtures() -> None:
    write_all()


def make_root(tmp_path: Path, *, project_config: Optional[dict[str, Any]] = None, saved: Optional[dict[str, Any]] = None,
              name: str = "proj") -> Path:
    root = tmp_path / name
    root.mkdir()
    if project_config is None:
        shutil.copy(PROJECT_ROOT / "council.config.json", root / "council.config.json")
    else:
        (root / "council.config.json").write_text(json.dumps(project_config))
    if saved is not None:
        (root / ".council").mkdir()
        (root / ".council" / "settings.json").write_text(json.dumps(saved))
    (root / "adapters" / "opencode").mkdir(parents=True)
    shutil.copy(PROJECT_ROOT / "adapters" / "opencode" / "opencode.json", root / "adapters" / "opencode" / "opencode.json")
    return root


def run_fixture(root: Path, fixture: str, *, run_id: str = "t", lenses: str = LENSES, preset: Optional[str] = None,
                overrides: Optional[dict[str, Any]] = None, strict: bool = True, question: str = QUESTION):
    # tests never reach a real model: the project's validation fallbacks (OpenCode models) are switched off unless a test asks
    ov: dict[str, Any] = {"routing": {"default_provider": "fixture", "validation_fallbacks": []}, "fixture_path": str(FIXTURES / fixture)}
    if lenses:
        ov["lenses"] = {"selection": "explicit", "explicit": lenses.split(",")}
    if overrides:
        _deep_update(ov, overrides)
    eff = load_effective_config(root, preset=preset, overrides=ov)
    store = Store.create(root / ".council" / "runs", run_id, question)
    store.data.effective_config = eff.config.model_dump(mode="json")
    store.data.provenance = eff.provenance
    store.save()
    engine = Engine(store, eff.config)
    providers = build_providers(eff.config, root, run_id)
    if not strict:
        providers["fixture"] = FixtureProvider(FIXTURES / fixture, strict_consumption=False)
    result = drive_until_chat_or_terminal(engine, providers)
    return engine, result


def _deep_update(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def events(engine: Engine) -> list[dict[str, Any]]:
    return [json.loads(l) for l in (engine.store.run_dir / "events.jsonl").read_text().splitlines()]
