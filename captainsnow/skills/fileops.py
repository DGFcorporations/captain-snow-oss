import aiofiles
from pathlib import Path
from .base import Skill


class FileopsSkill(Skill):
    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        if "create file" in prompt or "write file" in prompt:
            return await self._create_file(prompt)
        if "read file" in prompt:
            return await self._read_file(prompt)
        if "list files" in prompt:
            return await self._list_files()
        return "File operation not understood."

    def _root(self) -> Path:
        fileops_config = self.config.get("fileops") or {}
        configured = fileops_config.get("root") or "./captainsnow_files"
        root = Path(configured).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _confined_path(self, path: str) -> Path:
        root = self._root()
        requested = Path(path).expanduser()
        resolved = (requested if requested.is_absolute() else root / requested).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError("path must stay within the configured fileops root") from None
        return resolved

    async def _create_file(self, prompt: str) -> str:
        parts = prompt.split("with content", 1)
        if len(parts) != 2:
            return "Format: create file PATH with content CONTENT"
        path_part = parts[0].replace("create file", "", 1).strip()
        content = parts[1].strip()
        try:
            path = self._confined_path(path_part)
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, "w") as f:
                await f.write(content)
            return f"File created: {path}"
        except Exception as e:
            return f"Error creating file: {e}"

    async def _read_file(self, prompt: str) -> str:
        path_part = prompt.replace("read file", "", 1).strip()
        try:
            path = self._confined_path(path_part)
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
            return content[:1000]
        except Exception as e:
            return f"Error reading file: {e}"

    async def _list_files(self) -> str:
        try:
            return "\n".join(sorted(path.name for path in self._root().iterdir()))
        except Exception as e:
            return f"Error listing files: {e}"
