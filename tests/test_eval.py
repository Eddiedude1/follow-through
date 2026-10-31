import json

from eval import run_eval
from tests.conftest import FakeAnthropicClient, fake_text_response, fake_tool_use_response


def test_load_labeled_set_reads_json(tmp_path):
    p = tmp_path / "set.json"
    p.write_text(json.dumps([{"text": "x", "expected_types": ["ask"]}]))
    items = run_eval.load_labeled_set(str(p))
    assert items == [{"text": "x", "expected_types": ["ask"]}]


def test_evaluate_computes_perfect_precision_recall(tmp_path):
    p = tmp_path / "set.json"
    p.write_text(json.dumps([{"text": "take out the trash", "expected_types": ["ask"]}]))
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note",
            {"text": "take out the trash", "type": "ask", "source_date": "2026-10-31"}),
        fake_text_response("done"),
    ])
    report = run_eval.evaluate(str(p), client, model="claude-sonnet-5-5")
    assert report.precision == 1.0
    assert report.recall == 1.0


def test_sample_eval_set_is_valid():
    items = run_eval.load_labeled_set("eval/sample/labeled_notes.json")
    assert len(items) >= 5
    assert all(set(i["expected_types"]) <= {"ask", "preference", "context"} for i in items)
