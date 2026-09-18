"""Skill → OpenAI tool schema.

Every enabled skill is exposed to the agent loop as one function tool whose
single argument is a natural-language task string — the same `{prompt, action}`
payload `invoke_skill` has always taken. The skill's first docstring line
becomes the tool description, so a skill documents itself for the model.
"""

from typing import Dict, List
from skills.base import Skill


def skill_tool_schema(name: str, skill: Skill) -> dict:
    doc = (skill.__doc__ or f"Execute tasks related to {name}.").strip()
    description = " ".join(doc.split())
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Natural-language instruction for this skill — what to do and any details it needs.",
                    }
                },
                "required": ["task"],
            },
        },
    }


def build_tool_schemas(skills: Dict[str, Skill]) -> List[dict]:
    return [skill_tool_schema(name, skill) for name, skill in skills.items()]
