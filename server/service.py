from __future__ import annotations

import hashlib
import json
import random
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from statistics import fmean

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from .combo import CollectionError, generate_combos, rarity_report, theoretical_space, violates
from .crypto import encrypt
from .db import Database
from .images import (
    alpha_ratio,
    compose,
    cutout_flat_background,
    dhash,
    dominant_colors,
    hamming,
    open_image,
    remove_chroma,
    to_png_bytes,
)
from .prompts import (
    analysis_prompt,
    asset_prompt,
    concept_prompt,
    contract_prompt,
    cutout_prompt,
    plan_prompt,
    refine_prompt,
)
from .provider import ProviderClient, ProviderError, extract_json_object
from .settings import SUBJECT_MODES, project_dir
from .skills import get_skill
from .util import dumps, loads, now, uid

db = Database()


def reset_db() -> None:
    global db
    db = Database()


def provider_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "base_url": row["base_url"],
        "has_key": bool(row["api_key_enc"]),
        "vision_model": row.get("vision_model") or "",
        "text_model": row.get("text_model") or "",
        "image_model": row.get("image_model") or "",
        "edit_model": row.get("edit_model") or "",
        "image_api": row.get("image_api") or "openai_images",
        "is_default": bool(row.get("is_default")),
        "created_at": row["created_at"],
    }


def file_view(row: dict) -> dict:
    meta = loads(row.get("meta_json"), {})
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "kind": row["kind"],
        "label": row.get("label") or "",
        "meta": meta,
        "url": f"/api/files/{row['id']}",
        "created_at": row["created_at"],
    }


def nft_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "token_id": row["token_id"],
        "url": f"/api/nfts/{row['id']}/image?v={Path(row['image_path']).stem}",
        "attributes": loads(row["attributes_json"], []),
        "locked": bool(row["locked"]),
        "flagged": bool(row["flagged"]),
        "flag_reason": row.get("flag_reason") or "",
        "created_at": row["created_at"],
    }


def project_view(row: dict, with_nfts: bool = False) -> dict:
    files = [file_view(item) for item in db.q(
        "SELECT * FROM files WHERE project_id=? AND kind!='trial' ORDER BY created_at", (row["id"],)
    )]
    nft_count = db.one("SELECT COUNT(*) AS n FROM nfts WHERE project_id=?", (row["id"],))
    flagged = db.one("SELECT COUNT(*) AS n FROM nfts WHERE project_id=? AND flagged=1", (row["id"],))
    view = {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "target_count": row["target_count"],
        "width": row["width"],
        "height": row["height"],
        "style_notes": row.get("style_notes") or "",
        "subject_mode": row.get("subject_mode") or "recognizable",
        "skill_id": row.get("skill_id"),
        "status": row["status"],
        "provider_id": row.get("provider_id"),
        "analysis": loads(row.get("analysis_json"), None),
        "style_contract": loads(row.get("style_contract_json"), None),
        "plan": loads(row.get("plan_json"), {"categories": [], "rules": []}),
        "collection_seed": row.get("collection_seed"),
        "files": files,
        "nft_count": nft_count["n"] if nft_count else 0,
        "flagged_count": flagged["n"] if flagged else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    view["trial"] = trial_state(row)
    if with_nfts:
        view["nfts"] = [nft_view(item) for item in db.q("SELECT * FROM nfts WHERE project_id=? ORDER BY token_id", (row["id"],))]
    return view


def trial_signature(project: dict) -> str:
    anchors = db.q(
        "SELECT id FROM files WHERE project_id=? AND kind IN ('master','cutout') ORDER BY id",
        (project["id"],),
    )
    inputs = [project[key] for key in ("width", "height", "plan_json", "style_contract_json", "skill_id")]
    return hashlib.sha256(dumps([inputs, anchors]).encode()).hexdigest()


def trial_state(project: dict) -> dict:
    row = db.one("SELECT * FROM trials WHERE project_id=?", (project["id"],))
    if not row or row["signature"] != trial_signature(project):
        return {"ready": False, "approved": False, "images": []}
    return {"ready": True, "approved": bool(row["approved"]), "images": loads(row["images_json"], [])}


def approve_trial(project_id: str) -> dict:
    project = get_project(project_id)
    if not trial_state(project)["ready"]:
        raise CollectionError("请先生成并查看当前素材的样张")
    db.run("UPDATE trials SET approved=1 WHERE project_id=? AND signature=?", (project_id, trial_signature(project)))
    return project_view(project)


def get_project(project_id: str) -> dict:
    row = db.one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        raise KeyError("项目不存在")
    return row


def save_provider(payload: dict, provider_id: str | None = None) -> dict:
    name = (payload.get("name") or "").strip()
    base_url = (payload.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url:
        raise ValueError("请填写接口名称和 Base URL")
    try:
        parsed_url = httpx.URL(base_url)
    except httpx.InvalidURL as exc:
        raise ValueError("请输入有效的 HTTP(S) Base URL") from exc
    if not parsed_url.host or parsed_url.scheme not in {"http", "https"} or parsed_url.userinfo or parsed_url.query or parsed_url.fragment:
        raise ValueError("请输入不含凭据、查询参数或片段的 HTTP(S) Base URL")
    image_api = payload.get("image_api") or "openai_images"
    if image_api not in ("openai_images", "chat_image"):
        raise ValueError("不支持的出图方式")
    current = db.one("SELECT * FROM providers WHERE id=?", (provider_id,)) if provider_id else None
    if provider_id and not current:
        raise KeyError("找不到接口")
    api_key = payload.get("api_key") or ""
    if api_key:
        stored = encrypt(api_key)
    elif current and current["base_url"] == base_url:
        stored = current["api_key_enc"]
    else:
        stored = ""
    if payload.get("is_default"):
        db.run("UPDATE providers SET is_default=0")
    fields = (
        name,
        base_url,
        stored,
        payload.get("vision_model") or "",
        payload.get("text_model") or "",
        payload.get("image_model") or "",
        payload.get("edit_model") or "",
        image_api,
        1 if payload.get("is_default") else 0,
    )
    if current:
        db.run(
            """UPDATE providers SET name=?, base_url=?, api_key_enc=?, vision_model=?, text_model=?,
               image_model=?, edit_model=?, image_api=?, is_default=? WHERE id=?""",
            (*fields, provider_id),
        )
        row = db.one("SELECT * FROM providers WHERE id=?", (provider_id,))
    else:
        provider_id = uid()
        if not db.one("SELECT id FROM providers LIMIT 1"):
            fields = (*fields[:-1], 1)
        db.run(
            """INSERT INTO providers (id, name, base_url, api_key_enc, vision_model, text_model, image_model, edit_model, image_api, is_default, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (provider_id, *fields, now()),
        )
        row = db.one("SELECT * FROM providers WHERE id=?", (provider_id,))
    return provider_view(row)


def client_for(project: dict) -> ProviderClient:
    provider_id = project.get("provider_id")
    row = db.one("SELECT * FROM providers WHERE id=?", (provider_id,)) if provider_id else None
    if not row:
        row = db.one("SELECT * FROM providers WHERE is_default=1") or db.one("SELECT * FROM providers ORDER BY created_at LIMIT 1")
    if not row:
        raise ProviderError("还没有配置 API。请先在接口设置里填写 Base URL、密钥和模型。")
    return ProviderClient(row)


def create_project(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("请填写项目名称")
    mode = payload.get("subject_mode") or "recognizable"
    if mode not in SUBJECT_MODES:
        raise ValueError("未知的主体改动档位")
    count = int(payload.get("target_count") or 100)
    width = int(payload.get("width") or 1024)
    height = int(payload.get("height") or 1024)
    if not 1 <= count <= 10000:
        raise ValueError("数量需要在 1 到 10000 之间")
    if not 256 <= width <= 2048 or not 256 <= height <= 2048:
        raise ValueError("图片边长需要在 256 到 2048 之间")
    project_id = uid()
    stamp = now()
    db.run(
        """INSERT INTO projects (id, name, description, target_count, width, height, style_notes, subject_mode, skill_id, status, provider_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,'draft',?,?,?)""",
        (
            project_id,
            name,
            payload.get("description") or "",
            count,
            width,
            height,
            payload.get("style_notes") or "",
            mode,
            payload.get("skill_id") or "character-collection",
            payload.get("provider_id"),
            stamp,
            stamp,
        ),
    )
    return project_view(get_project(project_id))


def update_project(project_id: str, payload: dict) -> dict:
    row = get_project(project_id)
    mode = payload.get("subject_mode", row["subject_mode"])
    if mode not in SUBJECT_MODES:
        raise ValueError("未知的主体改动档位")
    if row["style_contract_json"] and (mode != row["subject_mode"] or payload.get("skill_id", row["skill_id"]) != row["skill_id"]):
        raise ValueError("主图锁定后，技能和主体改动档位也随之固定")
    count = int(payload.get("target_count", row["target_count"]))
    if not 1 <= count <= 10000:
        raise ValueError("数量需要在 1 到 10000 之间")
    db.run(
        """UPDATE projects SET name=?, description=?, target_count=?, style_notes=?, subject_mode=?, skill_id=?, provider_id=?, updated_at=? WHERE id=?""",
        (
            payload.get("name", row["name"]).strip() or row["name"],
            payload.get("description", row["description"]),
            count,
            payload.get("style_notes", row["style_notes"]),
            mode,
            payload.get("skill_id", row["skill_id"]),
            payload.get("provider_id", row["provider_id"]),
            now(),
            project_id,
        ),
    )
    return project_view(get_project(project_id))


def delete_project(project_id: str) -> None:
    get_project(project_id)
    db.run("DELETE FROM nfts WHERE project_id=?", (project_id,))
    db.run("DELETE FROM files WHERE project_id=?", (project_id,))
    db.run("DELETE FROM trials WHERE project_id=?", (project_id,))
    db.run("DELETE FROM jobs WHERE project_id=?", (project_id,))
    db.run("DELETE FROM projects WHERE id=?", (project_id,))
    folder = project_dir(project_id)
    if folder.exists():
        for path in sorted(folder.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        folder.rmdir()


def store_file(project_id: str, kind: str, label: str, image: Image.Image, meta: dict | None = None) -> dict:
    file_id = uid()
    folder = project_dir(project_id) / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{file_id}.png"
    image.save(path, format="PNG")
    db.run(
        "INSERT INTO files (id, project_id, kind, label, path, meta_json, created_at) VALUES (?,?,?,?,?,?,?)",
        (file_id, project_id, kind, label, str(path), dumps(meta or {}), now()),
    )
    return file_view(db.one("SELECT * FROM files WHERE id=?", (file_id,)))


def save_reference(project_id: str, raw: bytes) -> dict:
    project = get_project(project_id)
    if project["style_contract_json"]:
        raise ValueError("主图已锁定。更换参考图请新建系列。")
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("参考图不能超过 20MB")
    try:
        image = open_image(raw).convert("RGBA")
    except Exception as exc:
        raise ValueError("无法读取这张图片，请换 PNG、JPEG 或 WebP") from exc
    db.run("DELETE FROM files WHERE project_id=? AND kind IN ('reference','concept')", (project_id,))
    stored = store_file(project_id, "reference", "参考图", image, {"width": image.width, "height": image.height})
    touch(project_id, status="draft", analysis_json=None)
    return stored


def reference_image(project_id: str) -> tuple[dict, Image.Image, bytes]:
    row = db.one("SELECT * FROM files WHERE project_id=? AND kind='reference' ORDER BY created_at DESC LIMIT 1", (project_id,))
    if not row:
        raise ValueError("请先上传参考图")
    raw = Path(row["path"]).read_bytes()
    return file_view(row), open_image(raw).convert("RGBA"), raw


def touch(project_id: str, **fields) -> None:
    sets = ["updated_at=?"]
    params: list = [now()]
    for key, value in fields.items():
        sets.append(f"{key}=?")
        params.append(value)
    params.append(project_id)
    db.run(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", tuple(params))


def local_analysis(image: Image.Image) -> dict:
    return {
        "subject": "",
        "structure": "",
        "style": "",
        "palette": dominant_colors(image),
        "lighting": "",
        "composition": f"画面尺寸 {image.width}×{image.height}",
        "keep": [],
        "vary": [],
        "ambiguous": "这是没有调用模型的本地预分析。请自己补全主体，或配置视觉模型后重新分析。",
        "suggested_skill": "character-collection",
        "warnings": ["未使用 AI，不能自动识别主体。"],
        "source": "local",
    }


def normalize_analysis(data: dict, source: str) -> dict:
    def texts(key: str) -> list[str]:
        value = data.get(key) or []
        if isinstance(value, str):
            return [value] if value else []
        return [str(item) for item in value if str(item).strip()]

    skill_id = data.get("suggested_skill") or "character-collection"
    try:
        get_skill(skill_id)
    except StopIteration:
        skill_id = "character-collection"
    return {
        "subject": str(data.get("subject") or ""),
        "structure": str(data.get("structure") or ""),
        "style": str(data.get("style") or ""),
        "palette": texts("palette"),
        "lighting": str(data.get("lighting") or ""),
        "composition": str(data.get("composition") or ""),
        "keep": texts("keep"),
        "vary": texts("vary"),
        "ambiguous": str(data.get("ambiguous") or ""),
        "suggested_skill": skill_id,
        "warnings": texts("warnings"),
        "source": source,
    }


def normalize_plan(plan: dict) -> dict:
    categories = []
    for index, category in enumerate(plan.get("categories") or []):
        method = category.get("method")
        if method not in ("background", "patch", "overlay", "base"):
            method = "overlay"
        values = []
        for value_index, value in enumerate(category.get("values") or []):
            values.append(
                {
                    "id": str(value.get("id") or f"value-{index}-{value_index}"),
                    "name": str(value.get("name") or "未命名"),
                    "weight": max(1, min(100, int(value.get("weight") or 1))),
                    "prompt": str(value.get("prompt") or ""),
                    "asset_id": value.get("asset_id"),
                    "approved": bool(value.get("approved") and value.get("asset_id")),
                }
            )
        region = category.get("region") if isinstance(category.get("region"), dict) else None
        if method in ("overlay", "patch"):
            region = region or {"x": 0.34, "y": 0.12, "w": 0.32, "h": 0.24}
            try:
                x, y, w, h = (float(region[key]) for key in ("x", "y", "w", "h"))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("图层区域需要 x、y、w、h") from exc
            if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 - x + 1e-9 and 0 < h <= 1 - y + 1e-9):
                raise ValueError("图层区域必须在画布内，宽高须大于 0")
            region = {"x": x, "y": y, "w": w, "h": h}
        categories.append(
            {
                "id": str(category.get("id") or f"category-{index}"),
                "name": str(category.get("name") or "属性"),
                "z": int(category.get("z") if category.get("z") is not None else index * 10),
                "method": method,
                "region": region,
                "values": values,
            }
        )
    rules = []
    for rule in plan.get("rules") or []:
        if rule.get("type") in ("mutex", "requires") and rule.get("left") and rule.get("right"):
            rules.append({"type": rule["type"], "left": rule["left"], "right": rule["right"]})
    category_ids = {item["id"] for item in categories}
    value_ids = [value["id"] for item in categories for value in item["values"]]
    if len(category_ids) != len(categories) or len(set(value_ids)) != len(value_ids):
        raise ValueError("属性类别和版本的标识必须唯一")
    values = set(value_ids)
    if any(rule["left"] not in values or rule["right"] not in values for rule in rules):
        raise ValueError("规则引用了不存在的属性版本")
    categories.sort(key=lambda item: item["z"])
    return {"categories": categories, "rules": rules}


def api_size(width: int, height: int) -> str:
    if width == height and width in (256, 512, 1024):
        return f"{width}x{width}"
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


def fit_image(raw: bytes, width: int, height: int) -> Image.Image:
    image = open_image(raw).convert("RGBA")
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def analyze_project(project_id: str, progress) -> dict:
    project = get_project(project_id)
    if project["style_contract_json"]:
        raise ValueError("主图已锁定，分析结果已固定")
    _file, image, raw = reference_image(project_id)
    progress(20, "正在看参考图")
    try:
        client = client_for(project)
        if not client.vision_model:
            raise ProviderError("请在接口设置里为图片分析选择视觉模型")
        import base64

        encoded = base64.b64encode(raw).decode()
        text = client.chat(
            client.vision_model,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": analysis_prompt(project)},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                    ],
                }
            ],
            temperature=0.2,
        )
        analysis = normalize_analysis(extract_json_object(text), "model")
    except ProviderError as exc:
        if "还没有配置" in str(exc):
            analysis = local_analysis(image)
        else:
            raise
    progress(80, "正在整理分析结果")
    touch(project_id, analysis_json=dumps(analysis), skill_id=analysis["suggested_skill"], status="analyzed")
    return analysis


def generate_concepts(project_id: str, progress) -> list[dict]:
    project = get_project(project_id)
    if project["style_contract_json"]:
        raise ValueError("主图已锁定，请新建系列探索方向")
    analysis = loads(project.get("analysis_json"), None)
    if not analysis:
        raise ValueError("请先分析参考图，并确认主体。")
    if analysis.get("source") == "local" and not (analysis.get("subject") or "").strip():
        raise ValueError("本地预分析还不知道主体是什么。请先填写主体，或配置视觉模型后重新分析。")
    _file, _image, raw = reference_image(project_id)
    client = client_for(project)
    saved = []
    db.run("DELETE FROM files WHERE project_id=? AND kind='concept'", (project_id,))
    for index in range(3):
        progress(15 + index * 25, f"正在生成第 {index + 1} 张方向图")
        prompt = concept_prompt(project, analysis, index)
        image_bytes, sent = client.image_from_reference(
            prompt, api_size(project["width"], project["height"]), raw,
            require_reference=project["subject_mode"] == "strict",
        )
        image = fit_image(image_bytes, project["width"], project["height"])
        skill = get_skill(project.get("skill_id"))
        direction = skill["style_directions"][index]
        saved.append(
            store_file(
                project_id,
                "concept",
                direction["name"],
                image,
                {"direction": direction["name"], "reference_sent": sent, "index": index},
            )
        )
    touch(project_id, status="concepts")
    return saved


def refine_concept(project_id: str, file_id: str, instruction: str, progress) -> dict:
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("请写下要怎么改这张候选图")
    project = get_project(project_id)
    if project["style_contract_json"]:
        raise ValueError("主图已锁定，请新建系列精修候选图")
    row = db.one("SELECT * FROM files WHERE id=? AND project_id=? AND kind='concept'", (file_id, project_id))
    if not row:
        raise ValueError("找不到这张候选图")
    client = client_for(project)
    raw = Path(row["path"]).read_bytes()
    progress(30, "正在按你的描述精修")
    image_bytes, sent = client.image_from_reference(
        refine_prompt(project, instruction),
        api_size(project["width"], project["height"]),
        raw,
        require_reference=True,
    )
    image = fit_image(image_bytes, project["width"], project["height"])
    meta = loads(row.get("meta_json"), {})
    stored = store_file(
        project_id,
        "concept",
        f"{row.get('label') or '候选'} · 精修",
        image,
        {**meta, "parent_id": file_id, "instruction": instruction, "reference_sent": sent},
    )
    return stored


def default_contract(image: Image.Image, analysis: dict | None) -> dict:
    analysis = analysis or {}
    return {
        "summary": analysis.get("style") or "沿用锁定主图的渲染语言",
        "palette": analysis.get("palette") or dominant_colors(image),
        "line": "与主图一致",
        "lighting": analysis.get("lighting") or "与主图一致，不更换方向",
        "texture": "与主图一致",
        "crop": analysis.get("composition") or "与主图一致",
        "identity": analysis.get("keep") or [],
        "forbid": ["硬边贴纸", "混用另一种画风", "更换光照", "背景抢主体", "身份漂移"],
        "source": "local",
    }


def lock_master(project_id: str, file_id: str, progress) -> dict:
    project = get_project(project_id)
    row = db.one("SELECT * FROM files WHERE id=? AND project_id=?", (file_id, project_id))
    if not row or row["kind"] not in ("concept", "reference"):
        raise ValueError("请选择一张候选图或参考图作为主图")
    if project["style_contract_json"]:
        raise ValueError("这个系列已有锁定主图。请新建系列探索另一张主图。")
    progress(25, "正在锁定主图")
    image = open_image(Path(row["path"]).read_bytes()).convert("RGBA")
    image = image.resize((project["width"], project["height"]), Image.Resampling.LANCZOS)
    db.run("DELETE FROM files WHERE project_id=? AND kind='master'", (project_id,))
    master = store_file(project_id, "master", "锁定主图", image, {"source_file": file_id})
    analysis = loads(project.get("analysis_json"), {})
    contract = default_contract(image, analysis)
    try:
        client = client_for(project)
        if client.vision_model:
            progress(60, "正在提取风格合同")
            import base64

            text = client.chat(
                client.vision_model,
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": contract_prompt(project)},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + base64.b64encode(to_png_bytes(image)).decode()},
                            },
                        ],
                    }
                ],
                temperature=0.2,
            )
            parsed = extract_json_object(text)
            contract.update({key: parsed.get(key) or contract.get(key) for key in contract})
            contract["source"] = "model"
    except ProviderError:
        contract["source"] = "local"
    cutout = cutout_flat_background(image)
    if cutout is not None:
        db.run("DELETE FROM files WHERE project_id=? AND kind='cutout'", (project_id,))
        store_file(project_id, "cutout", "主体分离", cutout, {"source": "local"})
    touch(project_id, style_contract_json=dumps(contract), status="master_locked")
    return {"master": master, "style_contract": contract, "cutout": cutout is not None}


def save_style_contract(project_id: str, contract: dict) -> dict:
    with db.session() as conn:
        project = get_project(project_id)
        previous = loads(project["style_contract_json"], None)
        if not previous:
            raise ValueError("请先锁定主图")
        if any(previous.get(key) != value for key, value in contract.items()):
            plan = normalize_plan(loads(project["plan_json"], {}))
            for category in plan["categories"]:
                for value in category["values"]:
                    value["approved"] = False
            conn.execute(
                "UPDATE projects SET style_contract_json=?, plan_json=?, status='master_locked', updated_at=? WHERE id=?",
                (dumps({**contract, "source": "edited"}), dumps(plan), now(), project_id),
            )
            conn.execute("DELETE FROM trials WHERE project_id=?", (project_id,))
    return project_view(get_project(project_id))


def separate_subject(project_id: str, use_model: bool, progress) -> dict:
    project = get_project(project_id)
    row = db.one("SELECT * FROM files WHERE project_id=? AND kind='master' ORDER BY created_at DESC LIMIT 1", (project_id,))
    if not row:
        raise ValueError("请先锁定主图")
    image = open_image(Path(row["path"]).read_bytes()).convert("RGBA")
    source = "local"
    if use_model:
        progress(40, "正在让模型分离主体")
        client = client_for(project)
        raw, _ = client.image_from_reference(cutout_prompt(), api_size(project["width"], project["height"]), Path(row["path"]).read_bytes(), require_reference=True)
        image = remove_chroma(fit_image(raw, project["width"], project["height"]))
        source = "model"
    else:
        progress(40, "正在按纯色背景分离主体")
        cut = cutout_flat_background(image)
        if cut is None:
            raise ValueError("背景不是接近纯色，本地分离失败。可以改用模型分离，或换一张背景更干净的主图。")
        image = cut
    if alpha_ratio(image, transparent=True) < 0.05 or alpha_ratio(image, transparent=False) < 0.01:
        raise ValueError("分离结果须同时包含主体和透明区域，请换一种分离方式。")
    db.run("DELETE FROM files WHERE project_id=? AND kind='cutout'", (project_id,))
    stored = store_file(project_id, "cutout", "主体分离", image, {"source": source})
    return stored


def plan_traits(project_id: str, progress) -> dict:
    project = get_project(project_id)
    if not loads(project.get("style_contract_json"), None):
        raise ValueError("请先锁定主图")
    analysis = loads(project.get("analysis_json"), {})
    contract = loads(project.get("style_contract_json"), {})
    progress(30, "正在规划属性")
    client = client_for(project)
    model = client.text_model or client.vision_model
    text = client.chat(model, [{"role": "user", "content": plan_prompt(project, analysis, contract)}], temperature=0.4)
    plan = normalize_plan(extract_json_object(text))
    if not plan["categories"]:
        raise ProviderError("模型没有返回可用的属性计划")
    touch(project_id, plan_json=dumps(plan), status="traits_ready")
    return plan


def save_plan(project_id: str, plan: dict) -> dict:
    normalized = normalize_plan(plan)
    project = get_project(project_id)
    if not project["style_contract_json"]:
        raise ValueError("请先锁定主图")
    previous = loads(project["plan_json"], {"categories": []})
    old = {value["id"]: (category, value) for category in previous["categories"] for value in category["values"]}
    for category in normalized["categories"]:
        for value in category["values"]:
            prior_category, prior_value = old.get(value["id"], ({}, {}))
            asset_is_current = (
                all(category.get(key) == prior_category.get(key) for key in ("id", "method", "region"))
                and all(value.get(key) == prior_value.get(key) for key in ("prompt", "name"))
            )
            value["asset_id"] = prior_value.get("asset_id") if asset_is_current else None
            value["approved"] = bool(value["asset_id"] and prior_value.get("approved"))
    touch(project_id, plan_json=dumps(normalized), status="traits_ready")
    return normalized


def _load_asset(asset_id: str) -> Image.Image:
    row = db.one("SELECT * FROM files WHERE id=?", (asset_id,))
    if not row:
        raise ValueError("素材文件丢失")
    return open_image(Path(row["path"]).read_bytes()).convert("RGBA")


def generate_assets(project_id: str, progress, only_value: str | None = None) -> dict:
    project = get_project(project_id)
    plan = normalize_plan(loads(project.get("plan_json"), {}))
    contract = loads(project.get("style_contract_json"), None)
    if not contract:
        raise ValueError("请先锁定主图并确认风格合同")
    if not plan["categories"]:
        raise ValueError("请先规划属性")
    master = db.one("SELECT * FROM files WHERE project_id=? AND kind='master' ORDER BY created_at DESC LIMIT 1", (project_id,))
    if not master:
        raise ValueError("找不到锁定主图")
    client = client_for(project)
    reference = Path(master["path"]).read_bytes()
    targets = []
    for category in plan["categories"]:
        for value in category["values"]:
            if only_value and value["id"] != only_value:
                continue
            if value.get("approved") and not only_value:
                continue
            targets.append((category, value))
    if not targets:
        raise ValueError("没有需要生成的属性。已通过的素材会保留。")
    made = 0
    expected_plan = project["plan_json"]
    for index, (category, value) in enumerate(targets):
        progress(int(10 + 80 * index / max(1, len(targets))), f"正在生成 {category['name']} / {value['name']}")
        if value["name"].strip().lower() in {"无", "none"} and category["method"] in {"overlay", "patch"}:
            image = Image.new("RGBA", (1, 1))
            sent = None
            warning = ""
        else:
            raw, sent = client.image_from_reference(
                asset_prompt(project, contract, category, value),
                api_size(project["width"], project["height"]),
                reference,
                require_reference=True,
            )
            image = fit_image(raw, project["width"], project["height"])
            warning = ""
            if category["method"] == "patch":
                region = category["region"]
                x, y = int(region["x"] * image.width), int(region["y"] * image.height)
                w, h = max(1, int(region["w"] * image.width)), max(1, int(region["h"] * image.height))
                box = (x, y, x + w, y + h)
                image = image.crop(box)
                original = fit_image(reference, project["width"], project["height"]).crop(box)
                if not ImageChops.difference(image.convert("RGB"), original.convert("RGB")).getbbox():
                    warning = "局部编辑没有可见变化"
                margin = max(1, min(w, h) // 12)
                if min(w, h) > margin * 2:
                    mask = Image.new("L", image.size)
                    ImageDraw.Draw(mask).rectangle((margin, margin, w - margin - 1, h - margin - 1), fill=255)
                    image.putalpha(mask.filter(ImageFilter.GaussianBlur(margin / 2)))
            elif category["method"] in {"base", "overlay"}:
                image = remove_chroma(image)
                if alpha_ratio(image, transparent=True) < 0.04:
                    warning = "素材缺少透明区域，会遮住主体"
                elif alpha_ratio(image, transparent=False) < 0.01:
                    warning = "抠图后几乎没有可见内容"
        stored = store_file(
            project_id,
            "layer",
            f"{category['name']} / {value['name']}",
            image,
            {
                "category_id": category["id"],
                "value_id": value["id"],
                "method": category["method"],
                "reference_sent": sent,
                "warning": warning,
            },
        )
        value["asset_id"] = stored["id"]
        value["approved"] = False
        plan_json = dumps(plan)
        with db.session() as conn:
            changed = conn.execute(
                """UPDATE projects SET plan_json=?, status='assets_ready', updated_at=?
                   WHERE id=? AND plan_json=? AND style_contract_json=? AND skill_id=?""",
                (plan_json, now(), project_id, expected_plan, project["style_contract_json"], project["skill_id"]),
            )
            if not changed.rowcount:
                raise ValueError("生成期间属性或风格合同已变更，请刷新后重试")
        expected_plan = plan_json
        made += 1
    return {"created": made, "plan": plan}


def set_asset_approval(project_id: str, value_id: str, approved: bool) -> dict:
    project = get_project(project_id)
    plan = normalize_plan(loads(project.get("plan_json"), {}))
    found = False
    for category in plan["categories"]:
        for value in category["values"]:
            if value["id"] == value_id:
                if approved:
                    asset = db.one("SELECT * FROM files WHERE id=? AND project_id=? AND kind='layer'", (value.get("asset_id"), project_id))
                    if not asset:
                        raise ValueError("这项还没有素材，不能通过")
                    warning = loads(asset["meta_json"], {}).get("warning")
                    if warning:
                        raise ValueError(f"请先重做素材。{warning}")
                value["approved"] = approved
                found = True
    if not found:
        raise ValueError("找不到这个属性")
    touch(project_id, plan_json=dumps(plan))
    return plan


def attach_upload_asset(project_id: str, value_id: str, raw: bytes) -> dict:
    project = get_project(project_id)
    plan = normalize_plan(loads(project.get("plan_json"), {}))
    image = open_image(raw).convert("RGBA")
    target = None
    category = None
    for item in plan["categories"]:
        for value in item["values"]:
            if value["id"] == value_id:
                target = value
                category = item
    if not target or not category:
        raise ValueError("找不到这个属性")
    if category["method"] != "background":
        image = remove_chroma(image)
    stored = store_file(
        project_id,
        "layer",
        f"{category['name']} / {target['name']}",
        image,
        {"category_id": category["id"], "value_id": value_id, "method": category["method"], "uploaded": True},
    )
    target["asset_id"] = stored["id"]
    target["approved"] = False
    touch(project_id, plan_json=dumps(plan))
    return plan


def _cutout_image(project_id: str) -> Image.Image | None:
    row = db.one("SELECT * FROM files WHERE project_id=? AND kind='cutout' ORDER BY created_at DESC LIMIT 1", (project_id,))
    if not row:
        return None
    return open_image(Path(row["path"]).read_bytes()).convert("RGBA")


def render_choice(project: dict, plan: dict, choice: dict, cutout: Image.Image | None) -> Image.Image:
    layers = []
    used_base = False
    backgrounds = []
    overlays = []
    for category in sorted(plan["categories"], key=lambda item: item["z"]):
        value = choice.get(category["id"])
        if not value:
            continue
        image = _load_asset(value["asset_id"])
        if category["method"] == "background":
            backgrounds.append({"image": image, "method": "background"})
        elif category["method"] == "base":
            overlays.append({"image": image, "method": "character", "z": category["z"]})
            used_base = True
        else:
            method = category["method"]
            if method == "patch":
                meta = db.one("SELECT meta_json FROM files WHERE id=?", (value["asset_id"],))
                if not (meta and loads(meta["meta_json"], {}).get("reference_sent")):
                    method = "overlay"
            overlays.append({"image": image, "method": method, "region": category.get("region"), "z": category["z"]})
    if not backgrounds:
        color = (232, 224, 214, 255)
        backgrounds.append({"image": Image.new("RGBA", (project["width"], project["height"]), color), "method": "background"})
    if not used_base:
        if cutout is None:
            raise CollectionError("还没有可叠加的主体分离图。请先在主图步骤分离主体，或批准至少一张整体基底。")
        overlays.insert(0, {"image": cutout, "method": "character", "z": 5})
    overlays.sort(key=lambda item: item.get("z", 0))
    return compose(project["width"], project["height"], backgrounds + overlays)


def _attributes(plan: dict, choice: dict) -> list[dict]:
    attributes = []
    for category in plan["categories"]:
        value = choice.get(category["id"])
        if not value:
            continue
        attributes.append(
            {
                "trait_type": category["name"],
                "value": value["name"],
                "category_id": category["id"],
                "value_id": value["id"],
            }
        )
    return attributes


def _similarity_sample(image: Image.Image) -> tuple[int, Image.Image]:
    preview = image.resize((32, 32), Image.Resampling.LANCZOS)
    return dhash(image), preview.convert("RGB")


def _similar_reasons(samples: list[tuple[int, Image.Image]]) -> dict[int, str]:
    reasons = {}
    for i, (left_hash, left) in enumerate(samples):
        for j in range(i + 1, len(samples)):
            right_hash, right = samples[j]
            if hamming(left_hash, right_hash) > 6:
                continue
            difference = ImageChops.difference(left, right)
            if fmean(ImageStat.Stat(difference).rms) <= 4:
                reasons.setdefault(i, f"与 #{j + 1} 视觉接近")
                reasons.setdefault(j, f"与 #{i + 1} 视觉接近")
    return reasons


def _render_batch(project: dict, count: int, progress):
    plan = normalize_plan(loads(project.get("plan_json"), {}))
    if not plan["categories"]:
        raise CollectionError("请先规划并批准素材")
    space = theoretical_space(plan["categories"], plan["rules"])
    if space is not None and space < count:
        raise CollectionError(f"只有 {space} 种合法组合，少于所需的 {count} 张")
    seed = random.SystemRandom().randint(1, 2_000_000_000)
    combos = generate_combos(plan["categories"], plan["rules"], count, seed)
    cutout = _cutout_image(project["id"])
    folder = project_dir(project["id"]) / "renders" / uid()
    folder.mkdir(parents=True)
    rows, samples, exact = [], [], set()
    try:
        for index, choice in enumerate(combos, 1):
            if index == 1 or index == count or index % 10 == 0:
                progress(20 + int(70 * index / count), f"正在合成 {index}/{count}")
            image = render_choice(project, plan, choice, cutout)
            digest = hashlib.sha256(image.tobytes()).digest()
            if digest in exact:
                raise CollectionError("不同属性组合产生了像素完全一致的图片。请检查重叠图层或替换相同素材。")
            exact.add(digest)
            path = folder / f"{index}.png"
            image.save(path)
            samples.append(_similarity_sample(image))
            rows.append((path, _attributes(plan, choice)))
        progress(94, "正在检查视觉近似")
        return folder, rows, _similar_reasons(samples), seed
    except Exception:
        shutil.rmtree(folder)
        raise


def generate_trial(project_id: str, progress) -> dict:
    project = get_project(project_id)
    signature = trial_signature(project)
    plan = normalize_plan(loads(project.get("plan_json"), {}))
    space = theoretical_space(plan["categories"], plan["rules"])
    count = min(8, project["target_count"], space if space is not None else 8)
    if count < 1:
        raise CollectionError("没有可用组合，请先批准各类别的素材")
    folder, rows, reasons, _ = _render_batch(project, count, progress)
    images = []
    stamp = now()
    try:
        with db.session() as conn:
            if signature != trial_signature(get_project(project_id)):
                raise CollectionError("生成期间素材已变更，请重新试生成")
            for index, (path, attributes) in enumerate(rows):
                file_id = uid()
                images.append({"url": f"/api/files/{file_id}", "attributes": attributes, "warning": reasons.get(index, "")})
                conn.execute(
                    "INSERT INTO files (id, project_id, kind, label, path, created_at) VALUES (?,?,?,?,?,?)",
                    (file_id, project_id, "trial", f"样张 {index + 1}", str(path), stamp),
                )
            conn.execute(
                "INSERT OR REPLACE INTO trials (project_id, signature, images_json, approved) VALUES (?,?,?,0)",
                (project_id, signature, dumps(images)),
            )
    except Exception:
        shutil.rmtree(folder)
        raise
    return trial_state(project)


def _flag_similar(project_id: str) -> int:
    rows = db.q("SELECT * FROM nfts WHERE project_id=? ORDER BY token_id", (project_id,))
    samples = [_similarity_sample(open_image(Path(row["image_path"]).read_bytes())) for row in rows]
    reasons = _similar_reasons(samples)
    with db.session() as conn:
        conn.executemany("UPDATE nfts SET flagged=?, flag_reason=? WHERE id=?", [
            (int(index in reasons), reasons.get(index, ""), row["id"]) for index, row in enumerate(rows)
        ])
    return len(reasons)


def mint_collection(project_id: str, count: int, progress) -> dict:
    project = get_project(project_id)
    if not 1 <= count <= 10000:
        raise CollectionError("数量需要在 1 到 10000 之间")
    if not trial_state(project)["approved"]:
        raise CollectionError("请先确认当前素材的样张")
    if db.one("SELECT 1 FROM nfts WHERE project_id=? AND locked=1", (project_id,)):
        raise CollectionError("系列中有锁定的 NFT。请先解锁，或只重做未锁定的单张。")
    signature = trial_signature(project)
    folder, rows, reasons, seed = _render_batch(project, count, progress)
    try:
        with db.session() as conn:
            current = get_project(project_id)
            if signature != trial_signature(current) or not trial_state(current)["approved"]:
                raise CollectionError("生成期间样张验收已失效，请重新确认")
            if conn.execute("SELECT 1 FROM nfts WHERE project_id=? AND locked=1", (project_id,)).fetchone():
                raise CollectionError("系列中有锁定的 NFT。请先解锁，或只重做未锁定的单张。")
            conn.execute("DELETE FROM nfts WHERE project_id=?", (project_id,))
            conn.executemany(
                "INSERT INTO nfts (id,project_id,token_id,image_path,attributes_json,flagged,flag_reason,created_at) VALUES (?,?,?,?,?,?,?,?)",
                [(uid(), project_id, i + 1, str(path), dumps(attrs), int(i in reasons), reasons.get(i, ""), now())
                 for i, (path, attrs) in enumerate(rows)],
            )
            conn.execute("UPDATE projects SET status='generated', collection_seed=?, updated_at=? WHERE id=?", (seed, now(), project_id))
    except Exception:
        shutil.rmtree(folder)
        raise
    return {"count": count, "flagged": len(reasons), "seed": seed}



def reroll_nft(project_id: str, nft_id: str) -> dict:
    project = get_project(project_id)
    row = db.one("SELECT * FROM nfts WHERE id=? AND project_id=?", (nft_id, project_id))
    if not row:
        raise KeyError("找不到这张 NFT")
    if row["locked"]:
        raise CollectionError("这张已经锁定，不能重做")
    plan = normalize_plan(loads(project.get("plan_json"), {}))
    if not trial_state(project)["approved"]:
        raise CollectionError("请先确认当前素材的样张")
    existing = {
        tuple(sorted((item["category_id"], item["value_id"]) for item in loads(other["attributes_json"], [])))
        for other in db.q("SELECT attributes_json FROM nfts WHERE project_id=?", (project_id,))
    }
    candidates = generate_combos(plan["categories"], plan["rules"], 1, random.SystemRandom().randint(1, 2_000_000_000), exclude=existing)
    choice = candidates[0]
    image = render_choice(project, plan, choice, _cutout_image(project_id))
    _replace_nft_image(project_id, row, image, _attributes(plan, choice))
    updated = db.one("SELECT * FROM nfts WHERE id=?", (nft_id,))
    return nft_view(updated)


def _replace_nft_image(project_id: str, row: dict, image: Image.Image, attrs: list[dict]) -> None:
    folder = project_dir(project_id) / "edits"
    folder.mkdir(exist_ok=True)
    path = folder / f"{uid()}.png"
    pixels = image.tobytes()
    image.save(path)
    try:
        with db.session() as conn:
            for other in conn.execute("SELECT id, image_path, attributes_json, locked FROM nfts WHERE project_id=?", (project_id,)):
                if other["id"] == row["id"]:
                    if other["locked"] or other["image_path"] != row["image_path"]:
                        raise CollectionError("这张 NFT 已锁定或发生变更，请刷新后再试")
                    continue
                before = {attr["value_id"] for attr in loads(other["attributes_json"], [])}
                if before == {attr["value_id"] for attr in attrs}:
                    raise CollectionError("这组属性已用于另一张 NFT")
                if open_image(Path(other["image_path"]).read_bytes()).convert("RGBA").tobytes() == pixels:
                    raise CollectionError("这张图片与另一张 NFT 的像素完全相同")
            updated = conn.execute("UPDATE nfts SET image_path=?, attributes_json=? WHERE id=?", (str(path), dumps(attrs), row["id"]))
            if not updated.rowcount:
                raise CollectionError("系列已变更，请刷新后再试")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _flag_similar(project_id)


def update_nft(project_id: str, nft_id: str, payload: dict) -> dict:
    project = get_project(project_id)
    row = db.one("SELECT * FROM nfts WHERE id=? AND project_id=?", (nft_id, project_id))
    if not row:
        raise KeyError("找不到这张 NFT")
    if payload.get("values") is not None:
        if row["locked"] or not trial_state(project)["approved"]:
            raise CollectionError("请先解锁这张 NFT 并确认当前样张")
        plan = normalize_plan(loads(project.get("plan_json"), {}))
        lookup = {value["id"]: (category, value) for category in plan["categories"] for value in category["values"]}
        choice = {}
        for value_id in payload["values"]:
            if value_id not in lookup:
                raise ValueError("选择了不存在的属性")
            category, value = lookup[value_id]
            if not value.get("approved"):
                raise ValueError(f"「{value['name']}」还没有通过，不能用于成图")
            choice[category["id"]] = value
        if len(choice) != len(plan["categories"]) or len(payload["values"]) != len(choice) or violates(choice, plan["rules"]):
            raise CollectionError("每个类别请选择一个属性，并遵守互斥和依赖规则")
        image = render_choice(project, plan, choice, _cutout_image(project_id))
        _replace_nft_image(project_id, row, image, _attributes(plan, choice))
    if payload.get("locked") is not None:
        db.run("UPDATE nfts SET locked=? WHERE id=?", (int(payload["locked"]), nft_id))
    updated = db.one("SELECT * FROM nfts WHERE id=?", (nft_id,))
    return nft_view(updated)


def collection_stats(project_id: str) -> dict:
    get_project(project_id)
    rows = db.q("SELECT * FROM nfts WHERE project_id=? ORDER BY token_id", (project_id,))
    nfts = [{"attributes": loads(row["attributes_json"], []), "token_id": row["token_id"], "flagged": bool(row["flagged"])} for row in rows]
    report = rarity_report(nfts)
    report["flagged"] = sum(1 for row in rows if row["flagged"])
    return report


def export_zip(project_id: str) -> Path:
    project = get_project(project_id)
    rows = db.q("SELECT * FROM nfts WHERE project_id=? ORDER BY token_id", (project_id,))
    if not rows:
        raise ValueError("还没有可导出的 NFT")
    path = project_dir(project_id) / "oriel-collection.zip"
    stats = collection_stats(project_id)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            token = row["token_id"]
            archive.write(row["image_path"], f"images/{token}.png")
            meta = {
                "name": f"{project['name']} #{token}",
                "description": project.get("description") or "",
                "image": f"../images/{token}.png",
                "attributes": [
                    {"trait_type": item["trait_type"], "value": item["value"]}
                    for item in loads(row["attributes_json"], [])
                ],
            }
            archive.writestr(f"metadata/{token}.json", json.dumps(meta, ensure_ascii=False, indent=2))
        archive.writestr("summary/rarity.json", json.dumps(stats, ensure_ascii=False, indent=2))
        archive.writestr(
            "summary/manifest.json",
            json.dumps(
                {
                    "name": project["name"],
                    "description": project.get("description") or "",
                    "count": len(rows),
                    "image_size": [project["width"], project["height"]],
                    "generator": "Oriel NFT",
                    "note": "导出文件不包含 API Key 或接口地址。",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return path


def safe_file(file_id: str) -> Path:
    row = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not row:
        raise KeyError("文件不存在")
    path = Path(row["path"]).resolve()
    root = project_dir(row["project_id"]).resolve()
    if root not in path.parents:
        raise KeyError("文件不存在")
    return path


def safe_nft_image(nft_id: str) -> Path:
    row = db.one("SELECT * FROM nfts WHERE id=?", (nft_id,))
    if not row:
        raise KeyError("文件不存在")
    path = Path(row["image_path"]).resolve()
    root = project_dir(row["project_id"]).resolve()
    if root not in path.parents:
        raise KeyError("文件不存在")
    return path


def create_job(project_id: str | None, kind: str) -> str:
    job_id = uid()
    stamp = now()
    with db.session() as conn:
        if project_id:
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError("项目不存在")
            if conn.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (project_id,)).fetchone():
                raise ValueError("这个项目已有任务正在运行")
        conn.execute(
            "INSERT INTO jobs (id, project_id, kind, status, progress, message, created_at, updated_at) VALUES (?,?,?,'queued',0,'',?,?)",
            (job_id, project_id, kind, stamp, stamp),
        )
    return job_id


def finish_job(job_id: str, status: str, message: str, result=None, progress: int = 100) -> None:
    db.run(
        "UPDATE jobs SET status=?, progress=?, message=?, result_json=?, updated_at=? WHERE id=?",
        (status, progress, message, dumps(result) if result is not None else None, now(), job_id),
    )


def job_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "project_id": row.get("project_id"),
        "kind": row["kind"],
        "status": row["status"],
        "progress": row["progress"],
        "message": row.get("message") or "",
        "result": loads(row.get("result_json"), None),
        "updated_at": row["updated_at"],
    }


def read_upload_image(raw: bytes) -> Image.Image:
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("图片不能超过 20MB")
    return open_image(raw).convert("RGBA")
