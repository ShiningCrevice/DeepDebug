"""Read the validated snapshot only; never fall back to the web server environment."""

import json

from deepdebug.agent.schemas import EnvironmentSnapshot


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_snapshot(text: str) -> tuple[EnvironmentSnapshot, dict]:
    """Return validated fields and original JSON values for evidence from one parse."""
    data = json.loads(text, object_pairs_hook=_unique_object)
    snapshot = EnvironmentSnapshot.model_validate(data)
    if snapshot.environment.mode != "snapshot":
        raise ValueError("imported data must declare snapshot mode")
    return snapshot, data
