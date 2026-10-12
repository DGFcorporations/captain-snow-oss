## 2024-05-18 - [Path Traversal in Agent Skills]
**Vulnerability:** The FileopsSkill allowed absolute paths or ".." traversals in file read/write/list operations, enabling access to the host's entire filesystem.
**Learning:** Agent skills are fundamentally remote code execution environments. If a user can prompt a skill to read/write files without boundary checks, they have system-level access. The agent must enforce root directory constraints on every filesystem interaction.
**Prevention:** Implement a `resolve()` and `relative_to(base_path)` check to ensure target paths definitively reside within the intended workspace root (e.g., repository directory) before taking any OS action.
