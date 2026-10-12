"""API 사용량·비용 계산. 캐시 파일 하나 = 실제 API 호출 하나 (캐시 적중은 호출이 없다)."""
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from llm import CachedLLM
from usage import PRICES, estimate_tokens, image_tokens, report, summarize


class Out(BaseModel):
    x: int


def test_cached_llm_stores_real_usage_with_response(tmp_path):
    class Inner:
        last_usage = None

        def structured(self, *, model, system, user, schema, tag=""):
            self.last_usage = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 50}
            return Out(x=1)

    llm = CachedLLM(Inner, tmp_path / "llm")
    llm.structured(model="gpt-4.1", system="s", user="u", schema=Out, tag="judge-55-a")
    [record] = [json.loads(p.read_text()) for p in (tmp_path / "llm").glob("*.json")]
    assert record["usage"] == {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 50}


def test_summary_prices_exact_usage_and_estimates_old_calls(tmp_path):
    llm_dir = tmp_path / "cache" / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "judge-55-a-1.json").write_text(json.dumps({
        "tag": "judge-55-a", "model": "gpt-4.1", "response": {"judgments": []},
        "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 100_000}}))
    (llm_dir / "structure-55-2.json").write_text(json.dumps({                     # 사용량 기록 이전 호출
        "tag": "structure-55", "model": "gpt-4.1", "response": {"title": "공고"}}))
    jev_dir = tmp_path / "cache" / "jev"
    jev_dir.mkdir()
    (jev_dir / "55-a-3.json").write_text(json.dumps({"model": "jev-1.13.0", "latency_s": 0.2,
                                                    "usage": {"input_tokens": 2_000_000, "output_tokens": 0},
                                                    "answers": {}}))
    rows = {(r.basis, r.model, r.stage): r for r in summarize(tmp_path)}
    exact = rows[("실측", "gpt-4.1", "판정")]
    assert (exact.calls, exact.input_tokens, exact.output_tokens) == (1, 1_000_000, 100_000)
    assert exact.cost == pytest.approx(2.00 + 0.8)                             # $2/M 입력 + $8/M 출력
    est = rows[("추정", "gpt-4.1", "구조화")]
    assert est.calls == 1 and est.input_tokens > 0
    assert rows[("실측", "jev-1.13.0", "판정(JEV)")].cost == pytest.approx(0.084)


def test_token_estimates():
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens("가나다") == 2
    assert image_tokens(1024, 1024) == 85 + 170 * 4                           # 768×768 → 2×2 조각
    assert image_tokens(860, 3170) == 85 + 170 * image_tokens.tiles(860, 3170)
    assert set(PRICES) >= {"gpt-4.1", "gpt-4.1-mini", "jev"}


def _write_calls(root):
    llm_dir = root / "cache" / "llm"
    llm_dir.mkdir(parents=True)
    for name, tag, inp in (("judge-55-a-1", "judge-55-a", 1_000_000), ("judge-77-a-2", "judge-77-a", 500_000)):
        (llm_dir / f"{name}.json").write_text(json.dumps({
            "tag": tag, "model": "gpt-4.1", "response": {},
            "usage": {"input_tokens": inp, "cached_input_tokens": 0, "output_tokens": 0}}))
    jev_dir = root / "cache" / "jev"
    jev_dir.mkdir()
    (jev_dir / "55-a-3.json").write_text(json.dumps({"model": "jev-1.13.0",
                                                    "usage": {"input_tokens": 1_000_000}, "answers": {}}))


def test_report_breaks_cost_down_by_posting_and_totals(tmp_path):
    _write_calls(tmp_path)
    r = report(tmp_path)
    assert r["total"]["calls"] == 3
    assert r["total"]["cost"] == pytest.approx(2.0 + 1.0 + 0.042)
    by_posting = {p["posting_id"]: p for p in r["postings"]}
    assert by_posting["55"]["calls"] == 2 and by_posting["55"]["cost"] == pytest.approx(2.042)
    assert by_posting["77"]["cost"] == pytest.approx(1.0)
    assert r["postings"][0]["posting_id"] == "55"                              # 비용 큰 순
    assert {row["stage"] for row in r["rows"]} == {"판정", "판정(JEV)"}
    assert r["prices"]["gpt-4.1"] == {"input": 2.0, "cached_input": 0.5, "output": 8.0}
    assert r["prices_as_of"] and r["measured_calls"] == 3
