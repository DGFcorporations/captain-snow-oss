import pytest
import os
from pathlib import Path
from captainsnow.skills.fileops import FileopsSkill
from captainsnow.core.model_router import ModelRouter
from captainsnow.core.memory import Memory

@pytest.fixture
def fileops_skill():
    # Provide simple mock dependencies
    class MockConfig(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class MockRouter:
        async def query(self, *args, **kwargs):
            return ""

    class MockMemory:
        pass

    return FileopsSkill(MockConfig(), MockRouter(), MockMemory())

@pytest.mark.asyncio
async def test_fileops_safe_path(fileops_skill, tmp_path, monkeypatch):
    # Change current working directory to tmp_path for the test
    monkeypatch.chdir(tmp_path)

    # Test valid creation
    res = await fileops_skill.execute({"prompt": "create file my_safe_file.txt with content safe content"})
    assert "File created" in res
    assert os.path.exists("my_safe_file.txt")

    # Test valid reading
    res = await fileops_skill.execute({"prompt": "read file my_safe_file.txt"})
    assert "safe content" in res

    # Test valid listing
    res = await fileops_skill.execute({"prompt": "list files"})
    assert "my_safe_file.txt" in res

@pytest.mark.asyncio
async def test_fileops_path_traversal(fileops_skill, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Attempt to write outside directory
    # Use a unique file name that definitely won't exist from previous tests
    res = await fileops_skill.execute({"prompt": "create file ../../../../../tmp/hacked_2.txt with content you got hacked"})
    assert "Access denied" in res
    assert not os.path.exists("../../../../../tmp/hacked_2.txt")

    # Attempt to read outside directory
    res = await fileops_skill.execute({"prompt": "read file ../../../../../etc/passwd"})
    assert "Access denied" in res

    # Attempt to list outside directory (by calling _list_files directly since execute doesn't parse it)
    res = await fileops_skill._list_files("../../../../../etc/")
    assert "Access denied" in res
