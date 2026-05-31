import json

from pf_helper.answer.querylog import log_query


def test_log_query_appends_jsonl(tmp_path):
    path = tmp_path / "ask_queries.jsonl"
    log_query(path, {"served_by": "agent", "question": "q1"})
    log_query(path, {"served_by": "cache", "question": "q2"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["served_by"] == "agent"
    assert json.loads(lines[1])["question"] == "q2"


def test_log_query_swallows_errors(tmp_path):
    # a directory where a file is expected -> open() fails; must not raise
    bad = tmp_path / "subdir"
    bad.mkdir()
    log_query(bad, {"served_by": "agent"})  # should not raise
