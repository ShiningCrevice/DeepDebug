"""Validate split isolation, input provenance, labels and a frozen file inventory."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from deepdebug.agent.decision import INSTRUCTIONS
from deepdebug.agent.schemas import EnvironmentSnapshot
from deepdebug.security.paths import AuthorizedRoot

CATEGORIES = {"cuda_oom", "device_mismatch", "dependency", "path", "configuration"}


def cases(root: Path) -> list[dict]:
    result = []
    for split, folder in (("dev", "dev"), ("test", "test_inputs")):
        for path in sorted((root / folder).glob("*/case.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            if case["split"] != split or case["case_id"] != path.parent.name:
                raise ValueError("case identity or split mismatch")
            case["group"] = case.get("group", "common")
            case["root"] = path.parent
            result.append(case)
    return result


def material_kind(name: str) -> str:
    if Path(name).suffix in {".txt", ".log"}:
        return "log"
    if Path(name).suffix == ".py":
        return "code"
    if name.endswith("snapshot.json"):
        return "snapshot"
    return "config"


def validate_dataset(root: Path) -> dict:
    entries = cases(root)
    ids = [entry["case_id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case IDs")
    splits = Counter(entry["split"] for entry in entries)
    if splits != {"dev": 10, "test": 30}:
        raise ValueError("benchmark requires 10 development and 30 test cases")
    families = {split: {c["family_id"] for c in entries if c["split"] == split} for split in splits}
    if families["dev"] & families["test"]:
        raise ValueError("case families overlap across splits")
    groups = Counter(c["group"] for c in entries if c["split"] == "test")
    if groups != {"common": 20, "insufficient": 4, "out_of_scope": 2, "attack": 4}:
        raise ValueError("test group counts differ from the plan")
    categories = Counter(
        c["category"] for c in entries if c["split"] == "test" and c["group"] == "common"
    )
    if categories != {category: 4 for category in CATEGORIES}:
        raise ValueError("common test categories must have four cases each")
    labels = json.loads((root / "gold" / "labels.json").read_text(encoding="utf-8"))
    if set(labels) != set(ids):
        raise ValueError("label inventory differs from cases")
    for entry in entries:
        files = entry["materials"]
        if not 1 <= len(files) <= 10 or len(files) != len(set(files)):
            raise ValueError("invalid material count")
        if not all(Path(name).parts[:1] == ("materials",) for name in files):
            raise ValueError("inputs must stay under materials")
        if material_kind(files[0]) != "log":
            raise ValueError("first material must be a log")
        texts = {}
        with AuthorizedRoot(entry["root"] / "materials") as allowed:
            for name in files:
                text = allowed.read(Path(name).relative_to("materials").as_posix()).decode("utf-8")
                if "\x00" in text:
                    raise ValueError("binary material")
                if material_kind(name) == "snapshot":
                    EnvironmentSnapshot.model_validate_json(text)
                texts[name] = text
        metadata = entry["metadata"]
        if type(metadata["synthetic"]) is not bool:
            raise ValueError("synthetic provenance is required")
        if not metadata["synthetic"] and not metadata.get("exit_code"):
            raise ValueError("captured cases need a nonzero process exit")
        label = labels[entry["case_id"]]
        if (
            label["expected_category"] != entry["category"]
            or label["synthetic"] != metadata["synthetic"]
        ):
            raise ValueError("label category or provenance mismatch")
        if (
            not label["acceptable_root_causes"]
            or not label["acceptable_fixes"]
            or not label["key_evidence"]
        ):
            raise ValueError("incomplete semantic rubric")
        for evidence in label["key_evidence"]:
            text = texts[evidence["file"]]
            if ("line" in evidence) == ("pointer" in evidence):
                raise ValueError("gold evidence needs exactly one location")
            if "line" in evidence:
                start, end = evidence["line"], evidence.get("end", evidence["line"])
                lines = text.splitlines()
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 1 <= start <= end <= len(lines)
                    or "\n".join(lines[start - 1 : end]) != evidence["content"]
                ):
                    raise ValueError("gold line evidence differs from input")
            if "pointer" in evidence:
                if not isinstance(evidence["pointer"], str) or not evidence["pointer"].startswith(
                    "/"
                ):
                    raise ValueError("gold field evidence needs a JSON pointer")
                value = json.loads(text)
                for token in evidence["pointer"].lstrip("/").split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    value = value[int(token)] if isinstance(value, list) else value[token]
                expected = (
                    evidence["content"]
                    if isinstance(value, str)
                    else json.loads(evidence["content"])
                )
                if value != expected:
                    raise ValueError("gold field evidence differs from input")
    return {
        "splits": dict(splits),
        "test_groups": dict(groups),
        "test_categories": dict(categories),
        "provenance": {
            split: dict(
                Counter(
                    "synthetic" if c["metadata"]["synthetic"] else "captured"
                    for c in entries
                    if c["split"] == split
                )
            )
            for split in splits
        },
        "families": {split: len(values) for split, values in families.items()},
    }


def inventory(root: Path) -> dict:
    counts = validate_dataset(root)
    paths = [root / "gold" / "labels.json", root / "rubric.md"]
    for entry in cases(root):
        paths.append(entry["root"] / "case.json")
        paths.extend(entry["root"] / name for name in entry["materials"])
    return {
        "counts": counts,
        "prompt_sha256": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
        "files": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        },
    }


def verify_frozen(root: Path) -> dict:
    frozen = json.loads((root / "frozen.json").read_text(encoding="utf-8"))
    actual = inventory(root)
    if actual != frozen:
        raise ValueError("dataset, labels or Agent instructions changed since freeze")
    return actual["counts"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["validate", "freeze", "verify"])
    parser.add_argument("--root", type=Path, default=Path("benchmark"))
    args = parser.parse_args()
    try:
        if args.operation == "freeze":
            data = inventory(args.root)
            with (args.root / "frozen.json").open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            result = data["counts"]
        else:
            result = (
                verify_frozen(args.root)
                if args.operation == "verify"
                else validate_dataset(args.root)
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        print("数据集验证失败：检查划分、标签证据、输入边界或冻结摘要。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
