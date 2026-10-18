import aiofiles
import os
from pathlib import Path
from .base import Skill

class FileopsSkill(Skill):
    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        if "create file" in prompt or "write file" in prompt:
            return await self._create_file(prompt)
        elif "read file" in prompt:
            return await self._read_file(prompt)
        elif "list files" in prompt:
            return await self._list_files(prompt)
        else:
            return "File operation not understood."

    async def _create_file(self, prompt: str) -> str:
        parts = prompt.split("with content")
        if len(parts) != 2:
            return "Format: create file PATH with content CONTENT"
        path_part = parts[0].replace("create file", "").strip()
        content = parts[1].strip()
        path = Path(path_part).resolve()
        if not path.is_relative_to(Path.cwd().resolve()):
            return "Error: Access denied. Path traversal detected."
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, 'w') as f:
            await f.write(content)
        return f"File created: {path}"

    async def _read_file(self, prompt: str) -> str:
        path_part = prompt.replace("read file", "").strip()
        path = Path(path_part).resolve()
        if not path.is_relative_to(Path.cwd().resolve()):
            return "Error: Access denied. Path traversal detected."
        try:
            async with aiofiles.open(path, 'r') as f:
                content = await f.read()
            return content[:1000]
        except Exception as e:
            return f"Error reading file: {e}"

    async def _list_files(self, prompt: str) -> str:
        directory = prompt.replace("list files", "").strip()
        if not directory:
            directory = "."
        path = Path(directory).resolve()
        if not path.is_relative_to(Path.cwd().resolve()):
            return "Error: Access denied. Path traversal detected."
        try:
            files = os.listdir(path)
            return "\n".join(files)
        except Exception as e:
            return f"Error listing files: {e}"
