import pytest
import os
import aiofiles
from pathlib import Path
from captainsnow.skills.fileops import FileopsSkill

@pytest.mark.asyncio
async def test_fileops_path_traversal():
    skill = FileopsSkill(config={}, router=None, memory=None)

    # Test read traversal
    res = await skill.execute({"prompt": "read file ../../../../../../../etc/passwd"})
    assert "Path traversal detected" in res

    # Test write traversal
    res = await skill.execute({"prompt": "create file ../../../../../../../tmp/hacked.txt with content youve_been_hacked"})
    assert "Path traversal detected" in res

    # Test list traversal
    res = await skill.execute({"prompt": "list files ../../../../../../../etc/"})
    assert "Path traversal detected" in res
