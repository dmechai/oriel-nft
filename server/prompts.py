from __future__ import annotations

import json

from .settings import SUBJECT_MODES
from .skills import consistency_text, get_skill


def subject_clause(mode: str) -> str:
    item = SUBJECT_MODES.get(mode) or SUBJECT_MODES["recognizable"]
    return f"主体改动档位：{item['label']}。{item['note']}"


def skill_clause(skill: dict) -> str:
    policy = skill.get("layer_policy") or {}
    lines = [
        f"使用技能：{skill['name']}。{skill['summary']}",
        "技能一致性：",
        *[f"- {line}" for line in skill.get("consistency", [])],
        "工作室总约束：",
        consistency_text(),
        f"图层策略：优先 {', '.join(policy.get('prefer', []))}。谨慎整体重绘 {', '.join(policy.get('edit_only', []))}。{policy.get('note', '')}",
    ]
    return "\n".join(lines)


def analysis_prompt(project: dict) -> str:
    skill = get_skill(project.get("skill_id"))
    return f"""
你是 NFT 系列的视觉分析员。请看参考图，判断它实际是什么，不要假设它一定是头像。
{subject_clause(project.get('subject_mode') or 'recognizable')}
{skill_clause(skill)}
用户偏好：{project.get('style_notes') or '无'}
只返回 JSON，不要解释：
{{
  "subject": "主体是什么",
  "structure": "外观和结构",
  "style": "艺术风格",
  "palette": ["#颜色"],
  "lighting": "光照",
  "composition": "构图",
  "keep": ["应保持不变的特征"],
  "vary": ["适合变化、可做成属性的元素"],
  "ambiguous": "如果有多个主体或含义不清，用一句话问用户；否则为空字符串",
  "suggested_skill": "character-collection | object-series | portrait-stylize | abstract-variation",
  "warnings": ["可能影响系列一致性的问题"]
}}
""".strip()


def concept_prompt(project: dict, analysis: dict, index: int) -> str:
    skill = get_skill(project.get("skill_id") or analysis.get("suggested_skill"))
    direction = skill["style_directions"][index % len(skill["style_directions"])]
    return f"""
基于参考图，做一张完整的系列定稿候选。这不是滤镜，也不是把新元素贴到旧图上。
{subject_clause(project.get('subject_mode') or 'recognizable')}
本张只探索这一个方向：{direction['name']}。{direction['instruction']}
三张候选之间画风必须明显不同；这一张内部必须统一。
分析：{json.dumps(analysis, ensure_ascii=False)}
用户补充：{project.get('style_notes') or '无'}
{skill_clause(skill)}
不要文字、水印、多联画或边框。输出一张完整图片。
""".strip()


def refine_prompt(project: dict, instruction: str) -> str:
    skill = get_skill(project.get("skill_id"))
    return f"""
在当前候选图上按用户的话精修，不要换成另一种画风。
用户要求：{instruction}
{subject_clause(project.get('subject_mode') or 'recognizable')}
{skill_clause(skill)}
保留这张候选已经确定的渲染语言。不要文字和水印。
""".strip()


def contract_prompt(project: dict) -> str:
    return f"""
观察这张已经锁定的主图，提取以后所有 NFT 都必须遵守的风格合同。
{subject_clause(project.get('subject_mode') or 'recognizable')}
只返回 JSON：
{{
  "summary": "一句话描述渲染语言",
  "palette": ["#颜色"],
  "line": "线条",
  "lighting": "光照方向和软硬",
  "texture": "材质",
  "crop": "裁切和构图",
  "identity": ["身份锚点"],
  "forbid": ["硬边贴纸", "混用另一种画风", "更换光照", "背景抢主体", "身份漂移"]
}}
""".strip()


def plan_prompt(project: dict, analysis: dict, contract: dict) -> str:
    skill = get_skill(project.get("skill_id"))
    return f"""
为锁定主图规划可组合的 NFT 属性。目标数量 {project.get('target_count')}。
优先规划能独立成层的属性。衣服、姿势、复杂特效不要做成随意贴纸；如果需要，method 用 base，并只给少量整体版本。
各类别的组合应用互斥和依赖规则后，至少要达到目标数量，并留出一些替换余量。至多规划一个背景类别和一个整体基底类别。
每个类别 3 到 6 个值。配件可含高权重的「无」，背景和整体基底应使用实际可绘制的版本。
{skill_clause(skill)}
分析：{json.dumps(analysis, ensure_ascii=False)}
风格合同：{json.dumps(contract, ensure_ascii=False)}
只返回 JSON：
{{
  "categories": [
    {{
      "id": "background",
      "name": "背景",
      "z": 0,
      "method": "background",
      "region": null,
      "values": [{{"id": "bg-dawn", "name": "晨雾", "weight": 40, "prompt": "具体视觉描述"}}]
    }}
  ],
  "rules": [{{"type": "mutex", "left": "headwear-hood", "right": "accessory-halo"}}]
}}
method 只能是 background、patch、overlay、base。
region 用 0 到 1 的 x,y,w,h，没有区域就用 null。
规则引用 value id。不要规划超过 5 个类别。
""".strip()


def asset_prompt(project: dict, contract: dict, category: dict, value: dict) -> str:
    skill = get_skill(project.get("skill_id"))
    method = category.get("method")
    if method == "patch":
        region = category.get("region")
        task = f"在完整参考图上只修改这个归一化矩形内的内容：{region}。保持镜头、位置和分辨率比例，返回整图，区域以外保持不变。"
    elif method == "background":
        task = "只画一张空背景，不要出现主体。背景不能比主体更抢眼。"
    elif method == "base":
        task = "从锁定主图重绘一个完整主体版本，保持身份、光照和渲染语言。不要换画风。输出完整图，主体放在纯绿幕 #00FF50 前。"
    else:
        task = "只画一个可叠加的配件，匹配主图的线条、材质和光照。放在纯绿幕 #00FF50 上，不要画完整角色，不要硬边白底。"
    return f"""
{task}
属性：{category.get('name')} / {value.get('name')}。{value.get('prompt') or ''}
风格合同：{json.dumps(contract, ensure_ascii=False)}
{skill_clause(skill)}
如果不能和主图保持同一渲染语言，不要勉强画成另一种风格。
""".strip()


def cutout_prompt() -> str:
    return (
        "把主体从背景中分离，完整保留主体的身份、比例和渲染语言。"
        "背景替换成均匀纯绿幕 #00FF50，不要改变主体，不要加阴影地板，不要加文字。"
    )
