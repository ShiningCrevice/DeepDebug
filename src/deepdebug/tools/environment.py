"""Read the validated snapshot only; never fall back to the web server environment."""

import json

from pydantic import ValidationError

from deepdebug.agent.schemas import EnvironmentSnapshot
from deepdebug.security.paths import MaterialError


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_snapshot(text: str) -> EnvironmentSnapshot:
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
        snapshot = EnvironmentSnapshot.model_validate(data)
        if snapshot.environment.mode != "snapshot":
            raise ValueError("imported data must declare snapshot mode")
        return snapshot
    except (ValueError, ValidationError, RecursionError) as exc:
        raise MaterialError(
            "环境快照格式无效；需使用带时区时间和 snapshot 模式的 v1 快照。"
        ) from exc
