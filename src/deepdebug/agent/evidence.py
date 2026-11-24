"""Session-local stable IDs for immutable observations, deduplicated by provenance."""

from deepdebug.agent.schemas import Evidence, unique_ids


class EvidenceRegistry:
    def __init__(self, evidence: list[Evidence] | None = None) -> None:
        self._items = [Evidence.model_validate(e).model_copy(deep=True) for e in evidence or []]
        unique_ids([e.evidence_id for e in self._items], "evidence IDs")

    def register(self, **observation: object) -> Evidence:
        number = max((int(e.evidence_id[1:]) for e in self._items), default=0) + 1
        candidate = Evidence(evidence_id=f"E{number:03}", **observation)
        key = candidate.model_dump_json(exclude={"evidence_id"})
        for item in self._items:
            if item.model_dump_json(exclude={"evidence_id"}) == key:
                return item.model_copy(deep=True)
        self._items.append(candidate)
        return candidate.model_copy(deep=True)

    def values(self) -> list[Evidence]:
        return [item.model_copy(deep=True) for item in self._items]
