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
