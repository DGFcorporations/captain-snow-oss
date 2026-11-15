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

    def _is_safe_path(self, path: Path) -> bool:
        try:
            return path.resolve().is_relative_to(Path.cwd().resolve())
        except ValueError:
            return False

    async def _create_file(self, prompt: str) -> str:
        # Expect: "create file path/to/file.txt with content Hello world"
        parts = prompt.split("with content")
        if len(parts) != 2:
            return "Format: create file PATH with content CONTENT"
        path_part = parts[0].replace("create file", "").strip()
        content = parts[1].strip()
        path = Path(path_part)
        if not self._is_safe_path(path):
            return "Error: Cannot write outside of the current directory."
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, 'w') as f:
            await f.write(content)
        return f"File created: {path}"

    async def _read_file(self, prompt: str) -> str:
        path_str = prompt.replace("read file", "").strip()
        path = Path(path_str)
        if not self._is_safe_path(path):
            return "Error: Cannot read outside of the current directory."
        try:
            async with aiofiles.open(path, 'r') as f:
                content = await f.read()
            return content[:1000]
        except Exception as e:
            return f"Error reading file: {e}"

    async def _list_files(self, directory=".") -> str:
        path = Path(directory)
        if not self._is_safe_path(path):
            return "Error: Cannot list files outside of the current directory."
        files = os.listdir(directory)
        return "\n".join(files)
