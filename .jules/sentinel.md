## 2025-02-14 - Fix Path Traversal in FileOps
**Vulnerability:** The FileOps skill allowed reading and writing arbitrary files outside the repository root using path traversal strings (e.g., ../../../etc/passwd).
**Learning:** The prompt inputs defining file targets lacked validation boundaries. Because the agent operations execute within the same process context, any read/write without boundaries could exploit host-level filesystem access.
**Prevention:** Used `pathlib.Path.resolve()` to normalize the path and `is_relative_to(Path.cwd().resolve())` to ensure file targets always fall within the designated secure base path.
