from pathlib import Path

from preprocessing.criteria import CriteriaSource, EvidenceRef, PostingCriteria, Requirement
from preprocessing.evaluate import Truth, TruthItem, evaluate, load_truth, similarity

TRUTH_DIR = Path(__file__).parent / "fixtures" / "criteria_truth"


def R(rid, text, priority="must", category="other", normalized=None):
    return Requirement(id=rid, text=text, normalized=normalized or text, priority=priority, category=category,
                       evidence=EvidenceRef(quote=text))


def crit(*reqs):
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id="55", snapshot_fetched_at="t0", image_sha256=[]),
        extracted_at="t1", models={}, title="t", job_family="f", requirements=list(reqs), suitable=bool(reqs),
    )


def T(text, priority="must", category="other", aliases=()):
    return TruthItem(text=text, priority=priority, category=category, aliases=list(aliases))


def test_similarity_ignores_spacing_and_punctuation_but_not_short_fragments():
    assert similarity("고등학교 졸업 이상", "고등학교 졸업이상") == 1.0
    assert similarity("야간근무 가능", "야간 근무 가능자") == 1.0       # 충분히 긴 포함 관계
    assert similarity("영어", "영어 회화 능통자") < 0.6                 # 짧은 조각은 포함으로 치지 않음


def test_evaluate_counts_matches_misses_extras_and_agreement():
    truth = Truth(posting_id="55", requirements=[
        T("고등학교 졸업 이상", "must", "education"),
        T("야간근무 가능", "must", "other"),
        T("인근거주자", "preferred", "other"),
    ])
    ev = evaluate(truth, crit(
        R("r1", "고등학교 졸업 이상", "must", "education"),
        R("r2", "야간 근무 가능자", "preferred", "other"),     # 필수/우대 불일치
        R("r3", "운전면허", "must", "certification"),          # 정답에 없음
    ))
    assert [(t.text, r.id) for t, r in ev.matched] == [("고등학교 졸업 이상", "r1"), ("야간근무 가능", "r2")]
    assert [t.text for t in ev.missed] == ["인근거주자"]
    assert [r.id for r in ev.extra] == ["r3"]
    assert (ev.recall, ev.precision, ev.must_recall) == (2 / 3, 2 / 3, 1.0)
    assert (ev.priority_agreement, ev.category_agreement) == (0.5, 1.0)


def test_aliases_are_used_for_matching():
    truth = Truth(posting_id="55", requirements=[T("장애인은 관련법에 의거 우대", "preferred",
                                                     aliases=["장애인 우대"])])
    ev = evaluate(truth, crit(R("r1", "장애인 우대", "preferred")))
    assert ev.recall == 1.0


def test_empty_cases():
    ev = evaluate(Truth(posting_id="55", requirements=[]), crit())
    assert (ev.recall, ev.precision, ev.must_recall) == (1.0, 1.0, 1.0)


def test_truth_fixtures_are_valid():
    files = sorted(TRUTH_DIR.glob("*.yaml"))
    assert [f.stem for f in files] == ["55162188", "55189170"]
    for f in files:
        truth = load_truth(f)
        assert truth.posting_id == f.stem
        assert any(t.priority == "must" for t in truth.requirements)
