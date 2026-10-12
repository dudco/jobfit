from preprocessing.criteria import CriteriaSource
from preprocessing.structure import LLMConditions, LLMPosition, LLMRequirement, StructuredPosting
from preprocessing.verify import build_criteria, find_quote

TRANSCRIPT = (
    "<!-- slice 00 image=0 part=0 -->\n## 지원자격\n- 고등학교 졸업 이상\n- 야간근무 가능\n\n"
    "<!-- slice 01 image=0 part=1 -->\n## 우대사항\n- 해당직무 근무경험자\n- 국가보훈대상자"
)
SRC = CriteriaSource(site="saramin", posting_id="55", snapshot_fetched_at="t0", image_sha256=["abc"])


def llm_req(text, priority="must", category="other", quote=None, positions=(), sensitive=False):
    return LLMRequirement(text=text, normalized=text, priority=priority, category=category,
                          positions=list(positions), min_years=None, min_education=None,
                          sensitive=sensitive, quote=text if quote is None else quote)


def build(reqs, positions=()):
    out = StructuredPosting(
        title="생산직 채용", company="OO", job_family="식품 생산", positions=list(positions),
        requirements=list(reqs),
        conditions=LLMConditions(employment_type="정규직", locations=["청주"], schedule="주 5일", others=[]),
    )
    return build_criteria(out, TRANSCRIPT, source=SRC, models={"transcribe": "v", "structure": "t"},
                          extracted_at="t1")


def test_find_quote_ignores_whitespace_differences():
    assert find_quote("- 고등학교  졸업\n이상", TRANSCRIPT) == TRANSCRIPT.index("- 고등학교")
    assert find_quote("대학교 졸업", TRANSCRIPT) is None
    assert find_quote(" ", TRANSCRIPT) is None


def test_ids_evidence_location_and_missing_quote_flag():
    c = build([
        llm_req("고등학교 졸업 이상", category="education", quote="- 고등학교 졸업 이상"),
        llm_req("해당직무 근무경험", "preferred", "experience", quote="- 해당직무 근무경험자"),
        llm_req("운전면허", quote="- 1종 보통 운전면허"),                    # 전사에 없는 인용
    ])
    assert [r.id for r in c.requirements] == ["r1", "r2", "r3"]
    assert [(r.evidence.image_index, r.evidence.slice_index) for r in c.requirements] == [
        (0, 0), (0, 1), (None, None)]
    assert c.requirements[2].flags == ["quote_not_found"]
    assert c.warnings == ["근거 인용을 전사에서 찾지 못함: r3"]
    assert c.suitable


def test_duplicates_merge_keeping_must_but_different_positions_stay_separate():
    c = build([
        llm_req("야간근무 가능", "preferred"),
        llm_req("야간근무  가능", "must"),                                  # 공백만 다른 중복
        llm_req("상경계열 우대", "preferred", "education", quote="- 고등학교 졸업 이상", positions=["재무"]),
        llm_req("상경계열 우대", "preferred", "education", quote="- 고등학교 졸업 이상", positions=["수급"]),
    ])
    assert [(r.id, r.text, r.priority, r.positions) for r in c.requirements] == [
        ("r1", "야간근무 가능", "must", []),
        ("r2", "상경계열 우대", "preferred", ["재무"]),
        ("r3", "상경계열 우대", "preferred", ["수급"]),
    ]


def test_no_requirements_means_unsuitable():
    c = build([])
    assert not c.suitable
    assert c.warnings == ["요건이 0개 — 이미지에 자격요건이 없는 공고(안내 배너 등)일 수 있음"]


def test_no_must_requirement_warns():
    c = build([llm_req("해당직무 근무경험", "preferred", quote="- 해당직무 근무경험자")])
    assert c.warnings == ["필수 요건이 없음 — 필수/우대 판별을 확인"]


def test_carries_sensitive_positions_and_conditions():
    c = build([llm_req("국가보훈대상자", "preferred", quote="- 국가보훈대상자", sensitive=True)],
              positions=[LLMPosition(name="생산직", group=None, duties="배합/성형/포장", location="청주")])
    assert c.requirements[0].sensitive is True
    assert c.positions[0].name == "생산직" and c.positions[0].duties == "배합/성형/포장"
    assert (c.conditions.employment_type, c.conditions.locations) == ("정규직", ["청주"])
    assert (c.title, c.company, c.job_family, c.source.posting_id) == ("생산직 채용", "OO", "식품 생산", "55")


def test_phrases_meaning_no_condition_are_dropped():
    c = build([
        llm_req("경력 무관", quote="- 고등학교 졸업 이상"),
        llm_req("전공무관(상경계열 우대)", "preferred", "education", quote="- 고등학교 졸업 이상"),  # 우대 부분은 요건
        llm_req("고등학교 졸업 이상", category="education", quote="- 고등학교 졸업 이상"),
    ])
    assert [(r.id, r.text) for r in c.requirements] == [("r1", "전공무관(상경계열 우대)"), ("r2", "고등학교 졸업 이상")]
    assert c.warnings == ["조건이 없음을 뜻하는 문구 제외: 경력 무관"]


def test_requirement_positions_must_name_known_positions():
    c = build([llm_req("화공 전공", category="education", quote="- 고등학교 졸업 이상", positions=["공정", "없는분야"])],
              positions=[LLMPosition(name="공정", group=None, duties=None, location=None)])
    assert c.requirements[0].flags == ["unknown_position"]
    assert c.warnings == ["모집분야 목록에 없는 분야를 가리키는 요건: r1"]
