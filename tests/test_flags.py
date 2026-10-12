from flags import FLAGS, describe


def test_every_flag_the_code_can_emit_has_a_korean_explanation():
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    emitted = set()
    for path in [src / "preprocessing" / "verify.py", src / "scoring" / "verify.py"]:
        emitted |= set(re.findall(r'"(quote_[a-z_]+|no_evidence|not_judged|unknown_position)"', path.read_text()))
    assert emitted and emitted <= set(FLAGS)


def test_describe_unknown_flag_falls_back_to_code():
    assert describe("quote_not_found").label == "근거 인용 없음"
    assert describe("quote_not_found").severity == "warning" and describe("quote_spliced").severity == "info"
    assert describe("something_new").label == "something_new"
