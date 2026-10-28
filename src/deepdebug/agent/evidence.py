"""Session-local stable IDs for immutable observations, deduplicated by provenance."""

from deepdebug.agent.schemas import Evidence


class EvidenceRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def register(self, **observation: object) -> Evidence:
        candidate = Evidence(evidence_id=f"E{len(self._items) + 1:03}", **observation)
        key = candidate.model_dump_json(exclude={"evidence_id"})
        if key not in self._items:
            self._items[key] = candidate
        return self._items[key].model_copy(deep=True)

    def values(self) -> list[Evidence]:
        return [item.model_copy(deep=True) for item in self._items.values()]
