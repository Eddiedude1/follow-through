import json
from dataclasses import dataclass, field

from follow_through import agent, db


@dataclass
class EvalReport:
    precision: float
    recall: float
    by_type: dict[str, dict] = field(default_factory=dict)
    total_examples: int = 0


def load_labeled_set(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def evaluate(labeled_set_path: str, client, model: str) -> EvalReport:
    examples = load_labeled_set(labeled_set_path)

    counts = {
        "ask": {"tp": 0, "fp": 0, "fn": 0},
        "preference": {"tp": 0, "fp": 0, "fn": 0},
        "context": {"tp": 0, "fp": 0, "fn": 0},
    }

    for example in examples:
        conn = db.connect(":memory:")
        db.init_schema(conn)
        agent.run_agent(conn, example["text"], client, model=model)

        expected = list(example["expected_types"])
        actual = [note["type"] for note in db.search_notes(conn, "")]
        conn.close()

        remaining_expected = list(expected)
        for type_ in actual:
            if type_ in remaining_expected:
                remaining_expected.remove(type_)
                counts[type_]["tp"] += 1
            else:
                counts[type_]["fp"] += 1
        for type_ in remaining_expected:
            counts[type_]["fn"] += 1

    total_tp = sum(c["tp"] for c in counts.values())
    total_fp = sum(c["fp"] for c in counts.values())
    total_fn = sum(c["fn"] for c in counts.values())

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0

    by_type = {}
    for type_, c in counts.items():
        type_precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 1.0
        type_recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 1.0
        by_type[type_] = {"precision": type_precision, "recall": type_recall}

    return EvalReport(
        precision=precision,
        recall=recall,
        by_type=by_type,
        total_examples=len(examples),
    )
