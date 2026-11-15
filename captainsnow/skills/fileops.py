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
            # Pass the specified path, removing the action prefix
            path = prompt.replace("list files", "").strip() or "."
            return await self._list_files(path)
        else:
            return "File operation not understood."

    def _is_safe_path(self, target: str) -> bool:
        """Prevent path traversal by ensuring all targets are within the repository."""
        base_path = Path.cwd().resolve()
        target_path = Path(target).resolve()
        try:
            target_path.relative_to(base_path)
            return True
        except ValueError:
            return False

    async def _create_file(self, prompt: str) -> str:
        # Expect: "create file path/to/file.txt with content Hello world"
        parts = prompt.split("with content")
        if len(parts) != 2:
            return "Format: create file PATH with content CONTENT"
        path_part = parts[0].replace("create file", "").strip()
        content = parts[1].strip()

        if not self._is_safe_path(path_part):
            return "Error: Path access denied (must be within repository)."

        path = Path(path_part)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, 'w') as f:
            await f.write(content)
        return f"File created: {path}"

    async def _read_file(self, prompt: str) -> str:
        path_part = prompt.replace("read file", "").strip()
        if not self._is_safe_path(path_part):
            return "Error: Path access denied (must be within repository)."

        try:
            async with aiofiles.open(path_part, 'r') as f:
                content = await f.read()
            return content[:1000]
        except Exception as e:
            return f"Error reading file: {e}"

    async def _list_files(self, directory=".") -> str:
        if not self._is_safe_path(directory):
            return "Error: Path access denied (must be within repository)."

        try:
            files = os.listdir(directory)
            return "\n".join(files)
        except Exception as e:
            return f"Error listing files: {e}"
