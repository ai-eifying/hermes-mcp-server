"""Direct database reader for Hermes sessions, messages, and skills.

Provides fast read access without going through WS RPC.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hermes-mcp.db_reader")


def _get_hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except ImportError:
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


class DBReader:
    """Read-only access to Hermes state: sessions index, messages, skills."""

    def __init__(self):
        self._db = None
        self._hermes_home = _get_hermes_home()

    @property
    def db(self):
        if self._db is None:
            try:
                from hermes_state import SessionDB
                self._db = SessionDB()
            except Exception as e:
                logger.warning("SessionDB unavailable: %s", e)
        return self._db

    # ── Sessions Index ──

    def get_sessions_index(self) -> dict:
        sessions_file = self._hermes_home / "sessions" / "sessions.json"
        if not sessions_file.exists():
            return {}
        try:
            return json.loads(sessions_file.read_text("utf-8"))
        except Exception as e:
            logger.debug("Failed to load sessions.json: %s", e)
            return {}

    def get_session_entry(self, session_key: str) -> Optional[dict]:
        return self.get_sessions_index().get(session_key)

    # ── Messages ──

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """Read messages from SessionDB by session_id."""
        db = self.db
        if not db:
            return []
        try:
            all_msgs = db.get_messages(session_id)
        except Exception as e:
            logger.warning("get_messages failed: %s", e)
            return []

        result = []
        for msg in all_msgs:
            role = msg.get("role", "")
            content = self._extract_content(msg)
            if content:
                result.append({
                    "id": msg.get("id", 0),
                    "role": role,
                    "content": content,
                    "timestamp": msg.get("timestamp", ""),
                })

        return result[-limit:]

    def get_messages_by_key(self, session_key: str, limit: int = 50) -> list[dict]:
        """Read messages using session_key (platform key)."""
        entry = self.get_session_entry(session_key)
        if not entry:
            return []
        session_id = entry.get("session_id", "")
        if not session_id:
            return []
        return self.get_messages(session_id, limit)

    # ── Channel Directory ──

    def get_channel_directory(self) -> dict:
        dir_file = self._hermes_home / "channel_directory.json"
        if not dir_file.exists():
            return {}
        try:
            return json.loads(dir_file.read_text("utf-8"))
        except Exception:
            return {}

    # ── Skills ──

    def list_skills(self, category: str = "") -> list[dict]:
        skills_dir = self._hermes_home / "skills"
        if not skills_dir.exists():
            return []

        result = []
        if category:
            cat_dir = skills_dir / category
            if cat_dir.exists():
                result.extend(self._scan_skill_category(cat_dir, category))
        else:
            for cat_dir in sorted(skills_dir.iterdir()):
                if cat_dir.is_dir() and not cat_dir.name.startswith("."):
                    result.extend(self._scan_skill_category(cat_dir, cat_dir.name))
        return result

    def read_skill(self, name: str) -> Optional[str]:
        skills_dir = self._hermes_home / "skills"
        if not skills_dir.exists():
            return None
        # Search across all categories
        for cat_dir in skills_dir.iterdir():
            if not cat_dir.is_dir():
                continue
            skill_file = cat_dir / name / "SKILL.md"
            if skill_file.exists():
                return skill_file.read_text("utf-8")
        return None

    def _scan_skill_category(self, cat_dir: Path, category: str) -> list[dict]:
        result = []
        for skill_dir in sorted(cat_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                text = skill_file.read_text("utf-8")
                desc = self._extract_skill_desc(text)
                result.append({
                    "name": skill_dir.name,
                    "category": category,
                    "description": desc,
                    "path": str(skill_file),
                })
            except Exception:
                pass
        return result

    @staticmethod
    def _extract_skill_desc(text: str) -> str:
        """Extract description from SKILL.md frontmatter."""
        lines = text.split("\n")
        in_front = False
        for line in lines:
            if line.strip() == "---":
                if in_front:
                    break
                in_front = True
                continue
            if in_front and line.startswith("description:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
        # Fallback: first non-empty line after frontmatter
        after = False
        for line in lines:
            if line.strip() == "---":
                after = not after if after else True
                continue
            if after and line.strip() and not line.startswith("#"):
                return line.strip()[:200]
        return ""

    @staticmethod
    def _extract_content(msg: dict) -> str:
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        parts.append(p.get("text", ""))
                    elif p.get("type") == "tool_use":
                        parts.append(f"[tool: {p.get('name', '?')}]")
                    elif p.get("type") == "tool_result":
                        parts.append("[tool result]")
                else:
                    parts.append(str(p))
            return "\n".join(parts)
        return str(content) if content else ""
