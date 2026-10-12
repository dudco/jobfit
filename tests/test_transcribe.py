from preprocessing.transcribe import SliceRef, slice_at, transcribe

from .fakes import FakeLLM


def refs(tmp_path, spec):
    out = []
    for i, (image_index, part) in enumerate(spec):
        p = tmp_path / f"{image_index:02d}_{part:02d}.png"
        p.write_bytes(b"x")
        out.append(SliceRef(path=p, image_index=image_index, part=part))
    return out


def test_transcribe_marks_slices_and_passes_previous_tail(tmp_path):
    llm = FakeLLM(vision=["  ## 지원자격\n- 대학 졸업\n- 영어성적\n- 병역필  ", "- 우대: 영어 회화"])
    out = transcribe(llm, refs(tmp_path, [(0, 0), (0, 1)]), model="v", posting_id="55")

    assert out == ("<!-- slice 00 image=0 part=0 -->\n## 지원자격\n- 대학 졸업\n- 영어성적\n- 병역필\n\n"
                   "<!-- slice 01 image=0 part=1 -->\n- 우대: 영어 회화")
    assert [tag for _, tag in llm.calls] == ["transcribe-55-00", "transcribe-55-01"]
    assert llm.vision_inputs[0]["user_text"] is None
    assert llm.vision_inputs[1]["user_text"].endswith("- 대학 졸업\n- 영어성적\n- 병역필")  # 마지막 3줄만
    assert "## 지원자격" not in llm.vision_inputs[1]["user_text"]


def test_slice_at_finds_the_slice_containing_an_offset(tmp_path):
    text = transcribe(FakeLLM(vision=["첫 조각", "둘째 조각"]), refs(tmp_path, [(0, 0), (1, 0)]),
                      model="v", posting_id="55")
    assert slice_at(text, text.index("첫 조각")) == (0, 0)
    assert slice_at(text, text.index("둘째 조각")) == (1, 1)
    assert slice_at("마커 없음", 0) == (None, None)
