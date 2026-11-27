from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = Path(os.environ.get("ORIEL_SKILLS", ROOT / "skills"))
VERSION = "0.1.0"

SUBJECT_MODES = {
    "strict": {
        "label": "严格保留",
        "note": "身份、轮廓和关键特征不变，只改画风、配色和光影。适合已经满意主体、只想换表现方式的图。",
    },
    "recognizable": {
        "label": "保留辨识",
        "note": "可以调整姿势、服装和构图，但必须还能认出是同一个主体。适合想做系列变化、又不想换成另一个角色的图。",
    },
    "inspiration": {
        "label": "仅取灵感",
        "note": "可以重塑主体，只保留主题或情绪。锁定后的一致性以新主图为准，不再保证像原图。",
    },
}

CONSISTENCY_RULES = [
    "一个系列只允许一张锁定主图和一份风格合同。",
    "属性可以变化，渲染语言不能变。调色范围、线条粗细、光照方向、材质、裁切和身份锚点必须沿用锁定主图。",
    "禁止硬边贴纸、写实与扁平混贴、每张图换一种光、背景抢主体、五官或比例漂移、明显接缝。",
    "三张概念图只用于锁定前选方向。锁定后禁止混用不同概念图的画风。",
    "不合格素材不得进入合成。做不到一致时重做或缩小属性，不用割裂的图凑数量。",
]


def data_dir() -> Path:
    path = Path(os.environ.get("ORIEL_DATA", ROOT / "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: str) -> Path:
    path = data_dir() / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path
