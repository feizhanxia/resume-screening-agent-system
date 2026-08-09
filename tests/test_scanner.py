from pathlib import Path

from resume_agent.scanning.scanner import scan_resume_root


def test_scanner_treats_first_level_directory_as_candidate(tmp_path: Path):
    root = tmp_path / "resumes"
    candidate = root / "张三" / "证明材料"
    candidate.mkdir(parents=True)
    (root / "张三" / "简历.txt").write_text("Python", encoding="utf-8")
    (candidate / "论文.pdf").write_bytes(b"not-a-real-pdf")
    (root / "未归属.pdf").write_bytes(b"unassigned")

    result = scan_resume_root(root)

    assert len(result.candidates) == 1
    assert result.candidates[0].display_name == "张三"
    assert {item.relative_path for item in result.candidates[0].files} == {
        "简历.txt",
        "证明材料/论文.pdf",
    }
    assert len(result.unassigned_files) == 1
    assert result.file_count == 2


def test_scanner_hash_changes_when_candidate_package_changes(tmp_path: Path):
    root = tmp_path / "resumes"
    folder = root / "A"
    folder.mkdir(parents=True)
    file = folder / "resume.txt"
    file.write_text("one", encoding="utf-8")
    first = scan_resume_root(root).candidates[0].package_hash
    file.write_text("two", encoding="utf-8")
    second = scan_resume_root(root).candidates[0].package_hash
    assert first != second
