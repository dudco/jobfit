from scoring.result import (CandidateScore, MatchResult, PositionScore, PostingRef, RequirementJudgment,
                            Weights, load_result, results_dir, save_result)


def sample() -> MatchResult:
    j = RequirementJudgment(requirement_id="r1", text="고졸 이상", priority="must", category="education",
                            status="met", quotes=["[학력] 고등학교 · 졸업"], reason="고졸", credit=1.0, contribution=70.0)
    ps = PositionScore(position=None, score=70, raw=70.0, must_met=1, must_total=1, preferred_met=0,
                       preferred_total=1, unmet_must=[], unknown=[], judgments=[j])
    cs = CandidateScore(rank=1, candidate_id="c1", name="김", score=70, raw=70.0, position=None,
                        positions=[ps], summary=["필수 1개 중 1개 충족"], excluded_sensitive=["보훈 우대"])
    return MatchResult(posting=PostingRef(site="saramin", posting_id="55", title="t", criteria_extracted_at="t0"),
                       matched_at="t1", model="m", weights=Weights(), candidates=[cs])


def test_weights_defaults_match_adr_0017():
    w = Weights()
    assert (w.must_share, w.gate, w.partial, w.unknown) == (0.7, 0.8, 0.5, 0.5)


def test_save_load_roundtrip_atomic(tmp_path):
    path = save_result(tmp_path, sample())
    assert path == results_dir(tmp_path, "saramin", "55") / "ranking.json"
    assert not list(path.parent.glob("*.tmp"))
    assert load_result(tmp_path, "saramin", "55") == sample()
    assert load_result(tmp_path, "saramin", "99") is None
