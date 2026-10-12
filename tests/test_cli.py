from typer.testing import CliRunner

import cli
from crawler import service
from crawler.snapshot import (
    PostingSnapshot, SourceRef, StoredFile, StoredImage, save_snapshot, snapshot_dir,
)


def snap(posting_id, title):
    return PostingSnapshot(
        source=SourceRef(site="saramin", posting_id=posting_id, url="u"),
        fetched_at="2026-10-12T00:00:00+00:00",
        title=title,
        detail_html=StoredFile(path="detail.html", sha256="x", bytes=1),
        images=[StoredImage(path="images/00.jpg", sha256="y", bytes=1, index=0, source_url="s",
                            format="JPEG", width=860, height=4000)],
        body_text_length=0,
        is_image_posting=True,
    )


def test_crawl_command_crawls_each_ref(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    seen = []

    def fake_crawl(ref, settings, *, client, refresh, log):
        seen.append((ref, refresh, settings.data_dir))
        return snap(ref, f"공고 {ref}")

    monkeypatch.setattr(service, "crawl", fake_crawl)
    result = CliRunner().invoke(cli.app, ["crawl", "111", "222", "--refresh"])
    assert result.exit_code == 0, result.output
    assert seen == [("111", True, tmp_path), ("222", True, tmp_path)]
    assert "111  이미지 1장  이미지 공고  공고 111" in result.output


def test_postings_lists_saved_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_snapshot(snapshot_dir(tmp_path, "saramin", "111"), snap("111", "회계팀"))
    result = CliRunner().invoke(cli.app, ["postings"])
    assert result.exit_code == 0, result.output
    assert "111" in result.output and "회계팀" in result.output


from preprocessing import service as preprocessing_service
from preprocessing.criteria import (
    CriteriaSource, EvidenceRef, PostingCriteria, Position, Requirement, criteria_dir, save_criteria,
)


def sample_criteria():
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id="55", snapshot_fetched_at="t0", image_sha256=["a"]),
        extracted_at="t1", models={"transcribe": "v", "structure": "t"},
        title="생산직 채용", job_family="식품 생산", positions=[Position(name="생산직")],
        requirements=[
            Requirement(id="r1", text="고졸 이상", normalized="고졸", priority="must", category="education",
                        evidence=EvidenceRef(quote="- 고졸 이상", image_index=0, slice_index=0)),
            Requirement(id="r2", text="보훈", normalized="보훈", priority="preferred", category="other",
                        sensitive=True, evidence=EvidenceRef(quote="- 보훈"), flags=["quote_not_found"]),
        ],
        suitable=True, warnings=["근거 인용을 전사에서 찾지 못함: r2"],
    )


def test_extract_command_uses_cached_llm_and_prints_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    seen = []

    def fake_extract(ref, settings, *, llm, refresh, log):
        seen.append((ref, refresh, type(llm).__name__, settings.data_dir))
        return sample_criteria()

    monkeypatch.setattr(preprocessing_service, "extract", fake_extract)
    result = CliRunner().invoke(cli.app, ["extract", "55", "--refresh"])
    assert result.exit_code == 0, result.output
    assert seen == [("55", True, "CachedLLM", tmp_path)]
    assert "55  요건 2개 (필수 1, 우대 1)  모집분야 1  ⚠ 1  생산직 채용" in result.output


def test_criteria_command_shows_requirements_and_warnings(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_criteria(criteria_dir(tmp_path, "saramin", "55"), sample_criteria())
    result = CliRunner().invoke(cli.app, ["criteria", "55"])
    assert result.exit_code == 0, result.output
    for text in ("r1", "고졸 이상", "img0/slice0", "r2", "⚠ 근거 인용을 전사에서 찾지 못함: r2"):
        assert text in result.output


def test_criteria_command_without_result_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(cli.app, ["criteria", "55"])
    assert result.exit_code == 1
    assert "jobfit extract 55" in result.output


def test_evaluate_command_prints_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_criteria(criteria_dir(tmp_path, "saramin", "55"), sample_criteria())
    truth = tmp_path / "truth.yaml"
    truth.write_text('posting_id: "55"\nrequirements:\n'
                     '  - {text: 고졸 이상, priority: must, category: education}\n'
                     '  - {text: 인근거주자, priority: preferred, category: other}\n', encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["evaluate", "55", "--truth", str(truth)])
    assert result.exit_code == 0, result.output
    assert "재현율 50%" in result.output and "정밀도 50%" in result.output
    assert "누락: 인근거주자" in result.output and "추가: r2 보훈" in result.output


# --- 스코어링 (스펙 03) ---

def _write_candidate(directory, cid="c1", label="perfect"):
    directory.mkdir(exist_ok=True)
    (directory / f"{cid}.json").write_text(
        '{"id": "%s", "name": "김", "meta": {"target_posting": "55", "label": "%s"}}' % (cid, label),
        encoding="utf-8")
    return directory


def test_match_command_calls_service_and_prints_ranking_with_labels(monkeypatch, tmp_path):
    from scoring import service as scoring_service

    from .test_result import sample

    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    d = _write_candidate(tmp_path / "cands")
    seen = []

    def fake_match(ref, settings, *, llm, candidates_dir, refresh, log):
        seen.append((ref, candidates_dir, refresh, type(llm).__name__))
        return sample()

    monkeypatch.setattr(scoring_service, "match", fake_match)
    result = CliRunner().invoke(cli.app, ["match", "55", "--candidates", str(d), "--refresh"])
    assert result.exit_code == 0, result.output
    assert seen == [("55", d, True, "CachedLLM")]
    for text in ("c1", "70", "perfect", "의도 순서"):
        assert text in result.output


def test_result_command_shows_requirement_evidence(monkeypatch, tmp_path):
    from scoring.result import save_result

    from .test_result import sample

    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_result(tmp_path, sample())
    d = _write_candidate(tmp_path / "cands")
    result = CliRunner(env={"COLUMNS": "200"}).invoke(
        cli.app, ["result", "55", "--candidate", "c1", "--candidates", str(d)])
    assert result.exit_code == 0, result.output
    for text in ("1위 c1", "70점", "고졸 이상", "충족", "[학력] 고등학교", "70.0", "필수 1개 중 1개 충족", "보훈 우대"):
        assert text in result.output
    ranking = CliRunner().invoke(cli.app, ["result", "55", "--candidates", str(d)])
    assert ranking.exit_code == 0 and "c1" in ranking.output


def test_result_command_without_result_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(cli.app, ["result", "55"])
    assert result.exit_code == 1
    assert "jobfit match 55" in result.output


def test_run_command_runs_pipeline_and_prints_ranking(monkeypatch, tmp_path):
    import pipeline

    from .test_result import sample

    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBFIT_CANDIDATES_DIR", str(_write_candidate(tmp_path / "cands")))
    seen = []

    def fake_run(ref, settings, *, llm, refresh, log):
        seen.append((ref, refresh, type(llm).__name__))
        return sample()

    monkeypatch.setattr(pipeline, "run", fake_run)
    result = CliRunner().invoke(cli.app, ["run", "55", "--refresh"])
    assert result.exit_code == 0, result.output
    assert seen == [("55", True, "CachedLLM")]
    assert "c1" in result.output and "70" in result.output


def test_serve_command_starts_uvicorn_with_app(monkeypatch, tmp_path):
    import uvicorn

    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    seen = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: seen.append((type(app).__name__, host, port)))
    result = CliRunner().invoke(cli.app, ["serve", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert seen == [("FastAPI", "127.0.0.1", 8123)]
