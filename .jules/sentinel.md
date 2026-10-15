## 2024-10-24 - Path Traversal in File Operations
**Vulnerability:** The FileopsSkill allowed path traversal, enabling an agent to potentially read, write, or list files outside the application workspace (e.g. `../../../etc/passwd` or accessing other user's files).
**Learning:** Raw user input or agent-generated paths were passed directly to `aiofiles.open()` and `os.listdir()` without validation, which assumes the underlying agent/LLM is benign. In autonomous systems, file skills need strict sandboxing.
**Prevention:** All paths in file operations should be resolved and checked against the current working directory boundary (`Path.cwd().resolve()`) using `is_relative_to()` before any action is taken.
