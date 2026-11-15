## 2024-10-06 - Path Traversal in FileopsSkill
**Vulnerability:** The Fileops skill blindly accepted any path from the LLM prompt without validating it against a base directory, allowing `read file ../../../etc/passwd` to leak arbitrary system files or `write file` to overwrite them.
**Learning:** This agent directly passes LLM-generated string inputs into `aiofiles.open()` without sandboxing. LLM hallucinations or malicious prompt injections could lead to critical system compromise.
**Prevention:** Always sanitize and resolve paths provided by the LLM by using `path.resolve().is_relative_to(Path.cwd().resolve())` before executing file operations.
