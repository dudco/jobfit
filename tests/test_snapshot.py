import json

from jobfit.crawler.snapshot import (
    PostingSnapshot, SourceRef, StoredFile, list_snapshots, load_snapshot, save_file, save_snapshot, snapshot_dir,
)


def make(posting_id="1"):
    return PostingSnapshot(
        source=SourceRef(site="saramin", posting_id=posting_id, url="u"),
        fetched_at="2026-10-12T00:00:00+00:00",
        detail_html=StoredFile(path="detail.html", sha256="x", bytes=1),
        body_text_length=0,
        is_image_posting=False,
    )


def test_save_file_writes_bytes_and_records_hash(tmp_path):
    f = save_file(tmp_path, "images/00.png", b"abc")
    assert (tmp_path / "images" / "00.png").read_bytes() == b"abc"
    assert (f.path, f.bytes) == ("images/00.png", 3)
    assert f.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_snapshot_roundtrip_with_atomic_write(tmp_path):
    d = snapshot_dir(tmp_path, "saramin", "1")
    assert load_snapshot(d) is None
    path = save_snapshot(d, make())
    assert path == tmp_path / "postings" / "saramin" / "1" / "snapshot.json"
    assert load_snapshot(d) == make()
    assert not list(d.glob("*.tmp"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1 and raw["source"]["method"] == "crawl"


def test_list_snapshots_is_sorted_and_tolerates_missing_dir(tmp_path):
    for pid in ("2", "1"):
        save_snapshot(snapshot_dir(tmp_path, "saramin", pid), make(pid))
    assert [s.source.posting_id for s in list_snapshots(tmp_path)] == ["1", "2"]
    assert list_snapshots(tmp_path / "empty") == []
