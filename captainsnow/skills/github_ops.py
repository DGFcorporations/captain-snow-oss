"""
GitHub Operations Skill — Manage repositories, issues, PRs, and files.
"""
from github import Github
import os
import json
import re
from .base import Skill

class GithubOpsSkill(Skill):
    """Manage GitHub repositories, read code, create issues, and commit files."""

    def __init__(self, config, router, memory):
        super().__init__(config, router, memory)
        # Use an environment variable or fallback to config if we add it
        # Actually, GitHub API usually requires GITHUB_TOKEN
        self.token = os.environ.get("GITHUB_API_KEY", "") or os.environ.get("GITHUB_TOKEN", "")

    async def execute(self, payload: dict) -> dict:
        if not self.token:
            return {"status": "error", "action": "github_ops", "details": "GITHUB_API_KEY or GITHUB_TOKEN not set in environment."}
            
        g = Github(self.token)
        prompt = payload.get("prompt", "")
        
        sub_action_prompt = (
            "Extract the GitHub action required from the user prompt.\\n"
            "Respond ONLY with a JSON format block like this:\\n"
            "{\\\"action\\\": \\\"list_repos|read_file|create_issue|commit_file\\\", \\\"repo\\\": \\\"Owner/RepoName\\\", \\\"path\\\": \\\"filepath\\\", \\\"content\\\": \\\"file content or issue title/body\\\", \\\"message\\\": \\\"commit message\\\"}\\n"
            f"Prompt: {prompt}"
        )
        
        try:
            raw = await self.router.query("You are a GitHub operations parser.", sub_action_prompt, complexity="medium")
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                return {"status": "error", "details": f"Failed to parse github sub-action from response: {raw}"}
            data = json.loads(match.group(0))
            
            action = data.get("action")
            repo_name = data.get("repo")
            
            if action == "list_repos":
                user = g.get_user()
                repos = [r.full_name for r in user.get_repos(sort="updated")[:15]]
                return {"status": "success", "action": "github_list", "details": ", ".join(repos)}
            
            elif action == "read_file":
                if not repo_name: return {"status": "error", "details": "Missing repo name."}
                repo = g.get_repo(repo_name)
                contents = repo.get_contents(data.get("path", ""))
                text = contents.decoded_content.decode()
                return {"status": "success", "action": "github_read", "details": f"File {data.get('path')}:\\n{text}"}
                
            elif action == "create_issue":
                if not repo_name: return {"status": "error", "details": "Missing repo name."}
                repo = g.get_repo(repo_name)
                issue = repo.create_issue(title=data.get("content", "New Issue")[:50], body=data.get("content", ""))
                return {"status": "success", "action": "github_issue", "details": f"Created issue #{issue.number}: {issue.html_url}"}
                
            elif action == "commit_file":
                if not repo_name: return {"status": "error", "details": "Missing repo name."}
                repo = g.get_repo(repo_name)
                path = data.get("path", "")
                content = data.get("content", "")
                message = data.get("message", "Auto-commit via Captain Snow")
                
                try:
                    # check if file exists
                    file_info = repo.get_contents(path)
                    repo.update_file(file_info.path, message, content, file_info.sha)
                    return {"status": "success", "action": "github_commit", "details": f"Updated {path} in {repo_name}"}
                except Exception:
                    repo.create_file(path, message, content)
                    return {"status": "success", "action": "github_commit", "details": f"Created {path} in {repo_name}"}

            else:
                return {"status": "error", "details": f"Unknown action {action}"}
                
        except Exception as e:
            return {"status": "error", "action": "github_ops", "details": str(e)}
