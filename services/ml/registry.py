from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime
import os, json, uuid
try:
    import joblib  # type: ignore
except ImportError:  # pragma: no cover - fallback for minimal envs
    import pickle

    class _PickleJoblib:
        @staticmethod
        def dump(obj: Any, filename):
            with open(filename, "wb") as fh:
                pickle.dump(obj, fh)

        @staticmethod
        def load(filename):
            with open(filename, "rb") as fh:
                return pickle.load(fh)

    joblib = _PickleJoblib()  # type: ignore


def _artifacts_dir() -> Path:
    return Path(os.getenv("ARTIFACTS_DIR", "artifacts"))


def _registry_path() -> Path:
    return _artifacts_dir() / "registry.json"


def _models_dir() -> Path:
    return _artifacts_dir() / "models"


@dataclass
class ModelMeta:
    name: str
    version: str
    created_at: str
    path: str
    metrics: Dict[str, float]
    tags: Dict[str, Any]
    alias: Optional[str] = None


def _load_index() -> Dict[str, Any]:
    p = _registry_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"models": {}, "aliases": {}}


def _save_index(idx: Dict[str, Any]) -> None:
    d = _artifacts_dir()
    d.mkdir(parents=True, exist_ok=True)
    _registry_path().write_text(json.dumps(idx, indent=2), encoding="utf-8")


def register_model(name: str, model_obj: Any, metrics: Dict[str, float] | None = None,
                   tags: Dict[str, Any] | None = None, version: Optional[str] = None,
                   alias: Optional[str] = None) -> ModelMeta:
    idx = _load_index()
    version = version or datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    _models_dir().mkdir(parents=True, exist_ok=True)
    path = _models_dir() / f"{name}__{version}.joblib"
    joblib.dump(model_obj, path)

    meta = ModelMeta(
        name=name,
        version=version,
        created_at=datetime.utcnow().isoformat(),
        path=str(path.as_posix()),
        metrics=metrics or {},
        tags=tags or {},
    )
    idx["models"].setdefault(name, [])
    idx["models"][name].append(asdict(meta))
    if alias:
        idx["aliases"].setdefault(name, {})
        idx["aliases"][name][alias] = version
        meta.alias = alias
    _save_index(idx)
    return meta


def list_models(name: Optional[str] = None) -> Dict[str, Any]:
    idx = _load_index()
    if name:
        return {"models": {name: idx["models"].get(name, [])}, "aliases": idx["aliases"].get(name, {})}
    return idx


def get_model_meta(name: str, version: Optional[str] = None, alias: Optional[str] = None) -> ModelMeta:
    idx = _load_index()
    if alias:
        version = idx["aliases"].get(name, {}).get(alias)
        if not version:
            raise FileNotFoundError(f"No alias '{alias}' for model '{name}'.")
    if not version:
        items = sorted(idx["models"].get(name, []), key=lambda m: m["created_at"], reverse=True)
        if not items:
            raise FileNotFoundError(f"No versions for model '{name}'.")
        return ModelMeta(**items[0])
    for m in idx["models"].get(name, []):
        if m["version"] == version:
            return ModelMeta(**m)
    raise FileNotFoundError(f"Model '{name}' version '{version}' not found.")


def promote_alias(name: str, version: str, alias: str = "production") -> None:
    idx = _load_index()
    _ = next((m for m in idx["models"].get(name, []) if m["version"] == version), None)
    if _ is None:
        raise FileNotFoundError(f"Model '{name}' version '{version}' not found.")
    idx["aliases"].setdefault(name, {})
    idx["aliases"][name][alias] = version
    _save_index(idx)


def load_model(name: str, version: Optional[str] = None, alias: Optional[str] = None) -> Any:
    meta = get_model_meta(name, version, alias)
    return joblib.load(meta.path)
