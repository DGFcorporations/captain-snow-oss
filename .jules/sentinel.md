## 2023-10-27 - Path Traversal in FileopsSkill
 **Vulnerability:** Unvalidated user input was passed directly to file operations (read/write) allowing path traversal outside the intended directory.
 **Learning:** In Python, using `Path(path_part)` without verifying its absolute location (`resolve().is_relative_to(workspace)`) leaves the application vulnerable to traversal attacks.
 **Prevention:** Implement a standard `_is_safe_path` helper that resolves paths and checks if they belong to the permitted working directory.
