"""Skills MCP tools — list and view Hermes skills."""

from __future__ import annotations

import json


def register_skill_tools(mcp, db):

    @mcp.tool()
    def hermes_skills_list(category: str = "") -> str:
        """List all installed Hermes skills with descriptions.

        Args:
            category: Optional category filter (e.g. "devops", "research", "mcp")
        """
        skills = db.list_skills(category=category)
        return json.dumps({
            "count": len(skills),
            "skills": skills,
        }, indent=2, ensure_ascii=False)

    @mcp.tool()
    def hermes_skill_view(name: str) -> str:
        """View the full content of a Hermes skill's SKILL.md.

        Args:
            name: Skill name (e.g. "hermes-agent", "native-mcp")
        """
        content = db.read_skill(name)
        if content is None:
            return json.dumps({"error": f"Skill not found: {name}"})
        return content
