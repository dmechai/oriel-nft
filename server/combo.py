from __future__ import annotations

import random
from collections import Counter
from itertools import product


class CollectionError(ValueError):
    pass


def approved_values(category: dict) -> list[dict]:
    values = []
    for value in category.get("values", []):
        if value.get("approved") and value.get("asset_id"):
            values.append(value)
    return values


def violates(choice: dict[str, dict], rules: list[dict]) -> bool:
    present = {value["id"] for value in choice.values()}
    for rule in rules:
        left = rule.get("left")
        right = rule.get("right")
        kind = rule.get("type")
        if kind == "mutex" and left in present and right in present:
            return True
        if kind == "requires" and left in present and right not in present:
            return True
    return False


def theoretical_space(categories: list[dict], rules: list[dict], limit: int = 20000) -> int | None:
    if not categories:
        return 0
    pools = [approved_values(category) for category in categories]
    if any(not pool for pool in pools):
        return 0
    product = 1
    for pool in pools:
        product *= len(pool)
        if product > limit:
            return None
    count = 0
    indexes = [0] * len(pools)
    while True:
        choice = {categories[i]["id"]: pools[i][indexes[i]] for i in range(len(pools))}
        if not violates(choice, rules):
            count += 1
        pos = len(pools) - 1
        while pos >= 0:
            indexes[pos] += 1
            if indexes[pos] < len(pools[pos]):
                break
            indexes[pos] = 0
            pos -= 1
        if pos < 0:
            break
    return count


def generate_combos(
    categories: list[dict], rules: list[dict], count: int, seed: int, *, exclude: set[tuple] | None = None
) -> list[dict]:
    if count < 1:
        raise CollectionError("生成数量至少为 1")
    usable = []
    for category in categories:
        values = approved_values(category)
        if not values:
            raise CollectionError(f"「{category.get('name', '未命名属性')}」还没有通过的素材，不能开始合成")
        usable.append((category, values))
    space = theoretical_space(categories, rules)
    if space == 0:
        raise CollectionError("当前没有可合成的属性组合")
    if space is not None and space < count:
        raise CollectionError(
            f"在现有互斥和依赖规则下只有 {space} 种合法组合，少于要生成的 {count} 张。请增加已通过素材，或放宽规则。不会用重复图凑数。"
        )
    rng = random.Random(seed)
    seen = set(exclude or ())
    result = []
    attempts = 0
    max_attempts = max(count * 80, 500)
    while len(result) < count and attempts < max_attempts:
        attempts += 1
        choice = {}
        for category, values in usable:
            weights = [max(1, int(value.get("weight") or 1)) for value in values]
            choice[category["id"]] = rng.choices(values, weights=weights, k=1)[0]
        if violates(choice, rules or []):
            continue
        signature = tuple(sorted((key, value["id"]) for key, value in choice.items()))
        if signature in seen:
            continue
        seen.add(signature)
        result.append(choice)
    if len(result) < count and space is not None:
        for values in product(*(values for _, values in usable)):
            choice = {category["id"]: value for (category, _), value in zip(usable, values)}
            signature = tuple(sorted((key, value["id"]) for key, value in choice.items()))
            if signature not in seen and not violates(choice, rules):
                result.append(choice)
                if len(result) == count:
                    break
    if len(result) < count:
        raise CollectionError(
            f"尝试 {attempts} 次后只得到 {len(result)} 种不重复组合，没有凑满 {count} 张。请增加素材或放宽规则。"
        )
    return result


def rarity_report(nfts: list[dict]) -> dict:
    counts: Counter[tuple[str, str]] = Counter()
    for nft in nfts:
        for attr in nft.get("attributes", []):
            counts[(attr["trait_type"], attr["value"])] += 1
    total = max(1, len(nfts))
    rows = [
        {
            "trait_type": trait,
            "value": value,
            "count": count,
            "percent": round(count * 100 / total, 2),
        }
        for (trait, value), count in sorted(counts.items())
    ]
    return {"total": len(nfts), "traits": rows}
