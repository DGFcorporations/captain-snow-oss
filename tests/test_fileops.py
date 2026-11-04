import asyncio

from skills.fileops import FileopsSkill


def _skill(root):
    return FileopsSkill({"fileops": {"root": str(root)}}, None, None)


def test_fileops_rejects_parent_traversal_for_read_and_write(tmp_path):
    root = tmp_path / "sandbox"
    outside = tmp_path / "outside.txt"
    outside.write_text("outside data")
    skill = _skill(root)

    read_result = asyncio.run(skill._read_file("read file ../outside.txt"))
    write_result = asyncio.run(
        skill._create_file("create file ../outside.txt with content changed")
    )

    assert read_result.startswith("Error reading file:")
    assert "path must stay within" in read_result
    assert write_result.startswith("Error creating file:")
    assert "path must stay within" in write_result
    assert outside.read_text() == "outside data"


def test_fileops_rejects_symlink_escape_for_read_and_write(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside data")
    (root / "escape.txt").symlink_to(outside)
    skill = _skill(root)

    read_result = asyncio.run(skill._read_file("read file escape.txt"))
    write_result = asyncio.run(
        skill._create_file("create file escape.txt with content changed")
    )

    assert read_result.startswith("Error reading file:")
    assert write_result.startswith("Error creating file:")
    assert outside.read_text() == "outside data"


def test_fileops_creates_and_reads_only_within_root(tmp_path):
    root = tmp_path / "sandbox"
    skill = _skill(root)
    created = asyncio.run(
        skill._create_file("create file nested/ok.txt with content hello")
    )

    assert created.startswith("File created:")
    assert (root / "nested" / "ok.txt").read_text() == "hello"
    assert asyncio.run(skill._read_file("read file nested/ok.txt")) == "hello"
