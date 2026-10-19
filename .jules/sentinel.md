## 2024-10-19 - File Operations Path Traversal
**Vulnerability:** FileopsSkill allowed path traversal, enabling read/write of arbitrary system files by accepting unchecked user input in paths.
**Learning:** Agent tools manipulating files on the host filesystem inherently risk path traversal vulnerabilities if paths aren't restricted to a designated workspace directory. The skill parsed `prompt` strings directly to a `Path` and accessed it.
**Prevention:** Implement strict workspace boundaries by verifying that resolved absolute paths always reside within the expected workspace (e.g., repository root) using `path.resolve().is_relative_to(Path.cwd().resolve())`.
