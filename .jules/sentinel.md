## 2025-02-28 - Path Traversal Prevention in FileopsSkill
**Vulnerability:** The agent's `FileopsSkill` allowed reading, writing, and listing files directly from prompts using user-supplied paths without validation. An attacker could use `../../../../etc/passwd` to read system files or overwrite critical files.
**Learning:** Agentic skills that accept arbitrary inputs for file paths must strictly resolve the path and verify it falls within the expected workspace boundary.
**Prevention:** Use `Path.resolve().is_relative_to(Path.cwd().resolve())` to securely enforce that requested file paths remain constrained to the repository root directory before performing operations.
