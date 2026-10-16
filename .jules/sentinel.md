## 2023-10-16 - Path Traversal in FileOps Skill
**Vulnerability:** The `FileopsSkill` allowed reading and writing arbitrary files on the host file system using `../` path traversal sequences because it didn't validate if the resolved path was inside the workspace directory.
**Learning:** Python's `pathlib.Path` concatenates relative paths without restriction. Directly opening user-supplied paths without `.resolve().is_relative_to(cwd)` check exposes the host filesystem to LFI (Local File Inclusion) or arbitrary file overwrites.
**Prevention:** Always use `path.resolve()` and `path.is_relative_to(base_dir)` to validate that any user-controlled file path remains securely within the intended workspace boundary before performing file I/O operations.
