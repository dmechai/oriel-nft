from __future__ import annotations

from PIL import Image, ImageDraw

from . import service
from .util import dumps, now, uid


def _size_canvas(size: int, color=(0, 0, 0, 0)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (size, size), color)
    return image, ImageDraw.Draw(image)


def _bg(size: int, kind: str) -> Image.Image:
    if kind == "paper":
        image, draw = _size_canvas(size, (239, 226, 207, 255))
        draw.ellipse((size * 0.12, size * 0.1, size * 0.88, size * 0.9), fill=(247, 238, 224, 255))
    elif kind == "night":
        image, draw = _size_canvas(size, (28, 36, 48, 255))
        draw.ellipse((size * 0.68, size * 0.12, size * 0.84, size * 0.28), fill=(236, 226, 196, 255))
    elif kind == "moss":
        image, draw = _size_canvas(size, (214, 224, 206, 255))
        draw.rectangle((0, int(size * 0.72), size, size), fill=(127, 154, 120, 255))
    else:
        image, draw = _size_canvas(size, (92, 48, 38, 255))
        draw.ellipse((size * -0.1, size * 0.45, size * 1.1, size * 1.15), fill=(196, 112, 74, 255))
    return image


def _character(size: int) -> Image.Image:
    image, draw = _size_canvas(size)
    ink = (58, 42, 34, 255)
    fur = (226, 165, 107, 255)
    belly = (246, 226, 200, 255)
    s = size
    draw.polygon([(s * 0.30, s * 0.40), (s * 0.38, s * 0.16), (s * 0.46, s * 0.38)], fill=fur, outline=ink)
    draw.polygon([(s * 0.70, s * 0.40), (s * 0.62, s * 0.16), (s * 0.54, s * 0.38)], fill=fur, outline=ink)
    draw.ellipse((s * 0.28, s * 0.28, s * 0.72, s * 0.74), fill=fur, outline=ink)
    draw.ellipse((s * 0.36, s * 0.48, s * 0.64, s * 0.72), fill=belly)
    draw.polygon([(s * 0.50, s * 0.50), (s * 0.46, s * 0.56), (s * 0.54, s * 0.56)], fill=(196, 107, 74, 255))
    draw.arc((s * 0.44, s * 0.56, s * 0.56, s * 0.64), 20, 160, fill=ink, width=max(2, size // 180))
    return image


def _eyes(size: int, kind: str) -> Image.Image:
    image, draw = _size_canvas(size)
    ink = (58, 42, 34, 255)
    y = size * 0.40
    pairs = ((size * 0.40, y), (size * 0.60, y))
    radius = size * 0.035
    for cx, cy in pairs:
        if kind == "closed":
            draw.arc((cx - radius, cy - radius * 0.4, cx + radius, cy + radius * 0.5), 200, 340, fill=ink, width=max(3, size // 140))
        elif kind == "amber":
            draw.ellipse((cx - radius, cy - radius * 0.55, cx + radius, cy + radius * 0.55), fill=(232, 164, 74, 255), outline=ink)
            draw.ellipse((cx - radius * 0.25, cy - radius * 0.35, cx + radius * 0.15, cy + radius * 0.25), fill=ink)
        elif kind == "wide":
            draw.ellipse((cx - radius * 1.2, cy - radius, cx + radius * 1.2, cy + radius), fill=(246, 240, 230, 255), outline=ink)
            draw.ellipse((cx - radius * 0.4, cy - radius * 0.45, cx + radius * 0.35, cy + radius * 0.4), fill=ink)
        else:
            draw.ellipse((cx - radius * 0.7, cy - radius * 0.7, cx + radius * 0.7, cy + radius * 0.7), fill=ink)
    return image


def _hat(size: int, kind: str) -> Image.Image:
    image, draw = _size_canvas(size)
    if kind == "none":
        return image
    ink = (58, 42, 34, 255)
    if kind == "leaf":
        draw.ellipse((size * 0.34, size * 0.12, size * 0.68, size * 0.30), fill=(127, 154, 120, 255), outline=ink)
        draw.line((size * 0.50, size * 0.16, size * 0.50, size * 0.28), fill=ink, width=max(2, size // 200))
    elif kind == "band":
        draw.rectangle((size * 0.30, size * 0.24, size * 0.70, size * 0.32), fill=(142, 78, 62, 255), outline=ink)
        draw.rectangle((size * 0.46, size * 0.22, size * 0.54, size * 0.34), fill=(226, 186, 92, 255), outline=ink)
    else:
        draw.polygon([(size * 0.42, size * 0.28), (size * 0.50, size * 0.08), (size * 0.58, size * 0.28)], fill=(232, 164, 74, 255), outline=ink)
        draw.rectangle((size * 0.46, size * 0.26, size * 0.54, size * 0.32), fill=(92, 48, 38, 255))
    return image


def _charm(size: int, kind: str) -> Image.Image:
    image, draw = _size_canvas(size)
    if kind == "none":
        return image
    ink = (58, 42, 34, 255)
    cx, cy, r = size * 0.66, size * 0.58, size * 0.045
    if kind == "bead":
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(143, 175, 168, 255), outline=ink)
    else:
        draw.polygon([(cx, cy - r * 1.4), (cx + r, cy), (cx, cy + r * 1.4), (cx - r, cy)], fill=(226, 186, 92, 255), outline=ink)
    return image


def build_sample(count: int = 24, size: int = 768) -> dict:
    project_id = uid()
    stamp = now()
    service.db.run(
        """INSERT INTO projects (id, name, description, target_count, width, height, style_notes, subject_mode, skill_id, status, provider_id, analysis_json, style_contract_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id,
            "灯狐样例",
            "离线样例，用来走通工作室。这些图层不是 AI 生成的。",
            count,
            size,
            size,
            "暖色、同一支墨线、背景保持安静。",
            "recognizable",
            "character-collection",
            "assets_ready",
            None,
            dumps(
                {
                    "subject": "一只圆头灯狐",
                    "structure": "正面半身，双耳、短吻、固定鼻头",
                    "style": "平涂插画，统一墨线",
                    "palette": ["#e2a56b", "#efe2cf", "#3a2a22"],
                    "lighting": "无方向性高光，靠色块区分",
                    "composition": "主体居中",
                    "keep": ["圆头", "耳形", "鼻头"],
                    "vary": ["背景", "眼睛", "头饰", "配饰"],
                    "ambiguous": "",
                    "suggested_skill": "character-collection",
                    "warnings": ["这是程序绘制的离线样例，不是模型分析。"],
                    "source": "sample",
                }
            ),
            dumps(
                {
                    "summary": "暖色平涂，墨线固定，背景不抢主体",
                    "palette": ["#e2a56b", "#efe2cf", "#3a2a22", "#7f9a78"],
                    "line": "同一粗细的墨线",
                    "lighting": "不使用写实侧光",
                    "texture": "平涂",
                    "crop": "居中半身",
                    "identity": ["圆头", "耳形", "鼻头"],
                    "forbid": ["硬边贴纸", "混用另一种画风", "更换光照", "背景抢主体", "身份漂移"],
                    "source": "sample",
                }
            ),
            stamp,
            stamp,
        ),
    )
    service.store_file(project_id, "reference", "参考图", _character(size), {"sample": True})
    service.store_file(project_id, "master", "锁定主图", _character(size), {"sample": True})
    service.store_file(project_id, "cutout", "主体分离", _character(size), {"source": "sample"})
    categories = [
        ("background", "背景", 0, "background", None, [("paper", "纸色", 40), ("night", "夜色", 25), ("moss", "苔色", 25), ("ember", "余烬", 10)]),
        ("eyes", "眼睛", 20, "patch", {"x": 0.32, "y": 0.34, "w": 0.36, "h": 0.16}, [("ink", "墨点", 40), ("amber", "琥珀", 30), ("wide", "圆眼", 20), ("closed", "合眼", 10)]),
        ("headwear", "头饰", 30, "overlay", {"x": 0.28, "y": 0.06, "w": 0.44, "h": 0.28}, [("none", "无", 45), ("leaf", "叶", 25), ("band", "额带", 20), ("lantern", "小灯", 10)]),
        ("charm", "配饰", 40, "overlay", {"x": 0.58, "y": 0.50, "w": 0.18, "h": 0.18}, [("none", "无", 60), ("bead", "珠", 25), ("diamond", "菱形", 15)]),
    ]
    plan_categories = []
    for cat_id, name, z, method, region, values in categories:
        stored_values = []
        for value_id, label, weight in values:
            if cat_id == "background":
                image = _bg(size, value_id)
            elif cat_id == "eyes":
                image = _eyes(size, value_id)
            elif cat_id == "headwear":
                image = _hat(size, value_id)
            else:
                image = _charm(size, value_id)
            saved = service.store_file(project_id, "layer", f"{name} / {label}", image, {"category_id": cat_id, "value_id": f"{cat_id}-{value_id}", "method": method})
            stored_values.append(
                {
                    "id": f"{cat_id}-{value_id}",
                    "name": label,
                    "weight": weight,
                    "prompt": label,
                    "asset_id": saved["id"],
                    "approved": True,
                }
            )
        plan_categories.append({"id": cat_id, "name": name, "z": z, "method": method, "region": region, "values": stored_values})
    plan = {"categories": plan_categories, "rules": [{"type": "mutex", "left": "headwear-lantern", "right": "charm-diamond"}]}
    service.touch(project_id, plan_json=dumps(plan), status="assets_ready")
    service.generate_trial(project_id, lambda *_: None)
    service.approve_trial(project_id)
    service.mint_collection(project_id, count, lambda *_: None)
    return service.project_view(service.db.one("SELECT * FROM projects WHERE id=?", (project_id,)))
