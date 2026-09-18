from core.tools import build_tool_schemas, skill_tool_schema
from skills.base import Skill


class _Echo(Skill):
    """Echoes the task back. For testing only."""

    async def execute(self, task):
        return task.get("prompt", "")


class _NoDocstring(Skill):
    async def execute(self, task):
        return ""


def test_schema_uses_first_docstring_line():
    schema = skill_tool_schema("echo", _Echo({}, None, None))
    fn = schema["function"]
    assert schema["type"] == "function"
    assert fn["name"] == "echo"
    assert "Echoes the task back" in fn["description"]
    assert fn["parameters"]["required"] == ["task"]
    assert fn["parameters"]["properties"]["task"]["type"] == "string"


def test_schema_falls_back_to_generic_description():
    schema = skill_tool_schema("mystery", _NoDocstring({}, None, None))
    assert "mystery" in schema["function"]["description"]


def test_build_tool_schemas_covers_all_skills():
    skills = {"a": _Echo({}, None, None), "b": _NoDocstring({}, None, None)}
    schemas = build_tool_schemas(skills)
    assert {s["function"]["name"] for s in schemas} == {"a", "b"}
