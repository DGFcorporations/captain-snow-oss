import aiofiles
import os
from pathlib import Path
from .base import Skill

class FileopsSkill(Skill):
    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        # Very simple: parse command-like action (create file, read, list)
        if "create file" in prompt or "write file" in prompt:
            return await self._create_file(prompt)
        elif "read file" in prompt:
            return await self._read_file(prompt)
        elif "list files" in prompt:
            return await self._list_files()
        else:
            return "File operation not understood."

    def _get_safe_path(self, path_str: str) -> Path:
        base_dir = Path(".").resolve()
        target_path = Path(path_str).resolve()
        if not target_path.is_relative_to(base_dir):
            raise ValueError(f"Path traversal detected. Access denied to {path_str}")
        return target_path

    async def _create_file(self, prompt: str) -> str:
        # Expect: "create file path/to/file.txt with content Hello world"
        parts = prompt.split("with content")
        if len(parts) != 2:
            return "Format: create file PATH with content CONTENT"
        path_part = parts[0].replace("create file", "").strip()
        content = parts[1].strip()

        try:
            path = self._get_safe_path(path_part)
        except ValueError as e:
            return str(e)

        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, 'w') as f:
            await f.write(content)
        return f"File created: {path}"

    async def _read_file(self, prompt: str) -> str:
        path_str = prompt.replace("read file", "").strip()
        try:
            path = self._get_safe_path(path_str)
            async with aiofiles.open(path, 'r') as f:
                content = await f.read()
            return content[:1000]
        except Exception as e:
            return f"Error reading file: {e}"

    async def _list_files(self, directory=".") -> str:
        try:
            path = self._get_safe_path(directory)
            files = os.listdir(path)
            return "\n".join(files)
        except Exception as e:
            return f"Error listing files: {e}"
