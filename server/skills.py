from __future__ import annotations

import json
from functools import lru_cache

from .settings import CONSISTENCY_RULES, SKILLS_DIR

REQUIRED = ("id", "name", "summary", "consistency", "style_directions", "layer_policy")


def load_skills() -> list[dict]:
    skills = []
    if not SKILLS_DIR.exists():
        return skills
    for path in sorted(SKILLS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in REQUIRED if not data.get(key)]
        if missing:
            raise ValueError(f"{path.name} 缺少一致性字段：{', '.join(missing)}")
        if len(data["consistency"]) < 3:
            raise ValueError(f"{path.name} 的一致性约束太少，不能作为内置技能")
        if len(data["style_directions"]) < 3:
            raise ValueError(f"{path.name} 需要三种锁定前的风格方向")
        skills.append(data)
    return skills


def get_skill(skill_id: str | None) -> dict:
    skills = {item["id"]: item for item in load_skills()}
    if skill_id and skill_id in skills:
        return skills[skill_id]
    return skills.get("character-collection") or next(iter(skills.values()))


@lru_cache(maxsize=1)
def consistency_text() -> str:
    return "\n".join(f"- {line}" for line in CONSISTENCY_RULES)
