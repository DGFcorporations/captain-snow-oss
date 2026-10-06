## 2025-02-28 - Path Traversal Prevention in FileopsSkill
**Vulnerability:** The agent's `FileopsSkill` allowed reading, writing, and listing files directly from prompts using user-supplied paths without validation. An attacker could use `../../../../etc/passwd` to read system files or overwrite critical files.
**Learning:** Agentic skills that accept arbitrary inputs for file paths must strictly resolve the path and verify it falls within the expected workspace boundary.
**Prevention:** Use `Path.resolve().is_relative_to(Path.cwd().resolve())` to securely enforce that requested file paths remain constrained to the repository root directory before performing operations.
## 2025-02-28 - Path Traversal Prevention in File Generation and Memory
**Vulnerability:** Similar to `FileopsSkill`, `FileGenSkill` and `Memory`'s file store were vulnerable to path traversal because they accepted file names directly without sanitization. An attacker could use `../../` to write or read arbitrary system files.
**Learning:** Any skill or core module that reads or writes files based on user-supplied filenames must sanitize the filename before appending it to a base path.
**Prevention:** Use `os.path.basename(filename)` to strip any directory paths and ensure only the base filename is used. Additionally, for user-supplied extensions or formats, enforce alphanumeric constraints using `"".join(c for c in ext if c.isalnum())` to prevent format string injection or unexpected extension behaviors.
