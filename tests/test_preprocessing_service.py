from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from crawler.snapshot import PostingSnapshot, SourceRef, StoredImage, save_file, save_snapshot, snapshot_dir
from preprocessing.criteria import criteria_dir, load_criteria
from preprocessing.service import extract
from preprocessing.structure import LLMConditions, LLMRequirement, StructuredPosting
from settings import Settings

from .fakes import FakeLLM

STRUCTURED = StructuredPosting(
    title="생산직 채용", company="OO", job_family="식품 생산", positions=[],
    requirements=[LLMRequirement(text="고등학교 졸업 이상", normalized="고졸 이상", priority="must",
                                 category="education", positions=[], min_years=None,
                                 min_education="high_school", sensitive=False, quote="- 고등학교 졸업 이상")],
    conditions=LLMConditions(employment_type=None, locations=[], schedule=None, others=[]),
)
VISION = ["## 지원자격\n- 고등학교 졸업 이상"] + [f"- 기타 {i}" for i in range(9)]


def poster_bytes(height, width=720):
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for y in range(20, height - 40, 80):
        for x in range(10, width - 10, 12):
            draw.rectangle([x, y, x + 7, y + 30], fill="black")
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_snapshot(data_dir, heights=(1890,), with_html=True):
    d = snapshot_dir(data_dir, "saramin", "55")
    images = []
    for i, h in enumerate(heights):
        f = save_file(d, f"images/{i:02d}.png", poster_bytes(h))
        images.append(StoredImage(**f.model_dump(), index=i, source_url=f"https://img/{i}.png",
                                  format="PNG", width=720, height=h))
    snap = PostingSnapshot(
        source=SourceRef(site="saramin", posting_id="55", url="u"),
        fetched_at="2026-10-12T00:00:00+00:00",
        title="표시용 페이지 제목",
        view_html=save_file(d, "view.html", b"<title>page</title>"),
        detail_html=save_file(d, "detail.html", "<td style='font-size:0'>숨김: 회계 영업</td>".encode()),
        images=images, body_text_length=0, is_image_posting=bool(images),
    )
    save_snapshot(d, snap)
    if not with_html:
        (d / "view.html").unlink()
        (d / "detail.html").unlink()
    return snap


def settings(data_dir, slice_height=1000):
    return Settings(data_dir=data_dir, vision_model="v", text_model="t", slice_height=slice_height)


def test_extract_writes_slices_transcript_and_criteria(tmp_path):
    snap = make_snapshot(tmp_path)
    llm = FakeLLM(vision=list(VISION), structured=[STRUCTURED])
    c = extract("55", settings(tmp_path), llm=llm)

    out = criteria_dir(tmp_path, "saramin", "55")
    slices = sorted((out / "slices").glob("*.png"))
    vision_calls = [tag for kind, tag in llm.calls if kind == "vision"]
    assert len(slices) == len(vision_calls) >= 2                     # 1890px → 1000px 목표로 분할
    assert llm.calls[-1] == ("structured", "structure-55")
    assert (out / "transcript.md").read_text(encoding="utf-8").startswith("<!-- slice 00 image=0 part=0 -->")
    assert c.title == "생산직 채용"                                   # 이미지에서 읽은 제목 (페이지 제목 아님)
    assert c.requirements[0].evidence.slice_index == 0 and c.requirements[0].flags == []
    assert c.source.image_sha256 == [i.sha256 for i in snap.images]
    assert c.models == {"transcribe": "v", "structure": "t"}
    assert load_criteria(out) == c


def test_html_is_never_read(tmp_path):
    """ADR-0008: 스냅샷의 HTML을 지워도 결과가 같다."""
    make_snapshot(tmp_path / "a")
    with_html = extract("55", settings(tmp_path / "a"), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    make_snapshot(tmp_path / "b", with_html=False)
    without_html = extract("55", settings(tmp_path / "b"), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    assert with_html.model_dump(exclude={"extracted_at"}) == without_html.model_dump(exclude={"extracted_at"})


def test_slice_height_zero_sends_each_image_whole(tmp_path):
    make_snapshot(tmp_path, heights=(1890, 900))
    llm = FakeLLM(vision=list(VISION), structured=[STRUCTURED])
    extract("55", settings(tmp_path, slice_height=0), llm=llm)
    assert [tag for kind, tag in llm.calls if kind == "vision"] == ["transcribe-55-00", "transcribe-55-01"]


def test_second_extract_reuses_result_without_llm(tmp_path):
    make_snapshot(tmp_path)
    first = extract("55", settings(tmp_path), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    idle = FakeLLM()
    assert extract("55", settings(tmp_path), llm=idle) == first
    assert idle.calls == []


def test_refresh_extracts_again(tmp_path):
    make_snapshot(tmp_path)
    extract("55", settings(tmp_path), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    again = FakeLLM(vision=list(VISION), structured=[STRUCTURED])
    extract("55", settings(tmp_path), llm=again, refresh=True)
    assert again.calls[-1] == ("structured", "structure-55")


def test_missing_snapshot_raises_with_hint(tmp_path):
    with pytest.raises(RuntimeError, match="jobfit crawl 55"):
        extract("55", settings(tmp_path), llm=FakeLLM())


def test_snapshot_without_images_is_unsuitable_and_calls_no_llm(tmp_path):
    make_snapshot(tmp_path, heights=())
    idle = FakeLLM()
    c = extract("55", settings(tmp_path), llm=idle)
    assert not c.suitable and c.warnings == ["스냅샷에 본문 이미지가 없음"]
    assert idle.calls == []


def test_failure_leaves_no_criteria(tmp_path):
    make_snapshot(tmp_path)

    def boom(user):
        raise RuntimeError("API 오류")

    with pytest.raises(RuntimeError, match="API 오류"):
        extract("55", settings(tmp_path), llm=FakeLLM(vision=list(VISION), structured=[boom]))
    assert load_criteria(criteria_dir(tmp_path, "saramin", "55")) is None
