"""Per-category structured stat extraction from Foundry `system` data.

Returns an ordered tuple of (label, value) string pairs for get_entry's
category-aware header. Categories without a statblock return ().
All field paths are verified against the foundryvtt/pf2e repo.
"""

from __future__ import annotations

from collections.abc import Mapping


def _g(node: object, *path: str) -> object:
    cur = node
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _pairs(*items: tuple[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple((label, str(value)) for label, value in items if value is not None and value != "")


def _format_price(price: object) -> str | None:
    if not isinstance(price, Mapping):
        return None
    # Falsy guard intentionally omits zero/missing denominations (PF2e never
    # writes "0 gp, 1 sp"); a genuine integer 0 should not appear in a price.
    parts = [f"{price[c]} {c}" for c in ("pp", "gp", "sp", "cp") if price.get(c)]
    return ", ".join(parts) if parts else None


_ACTIVITY_WORDS = {1: "one action", 2: "two actions", 3: "three actions"}


def _activity(system: Mapping) -> str | None:
    action_type = _g(system, "actionType", "value")
    count = _g(system, "actions", "value")
    if action_type == "action" and isinstance(count, int):
        return _ACTIVITY_WORDS.get(count, f"{count} actions")
    if action_type in ("reaction", "free", "passive"):
        return action_type
    return action_type if isinstance(action_type, str) else None


def _creature(s: Mapping) -> tuple[tuple[str, str], ...]:
    fort, ref, will = (
        _g(s, "saves", "fortitude", "value"),
        _g(s, "saves", "reflex", "value"),
        _g(s, "saves", "will", "value"),
    )
    saves = None
    if all(isinstance(v, int) for v in (fort, ref, will)):
        saves = f"Fort {fort:+d}, Ref {ref:+d}, Will {will:+d}"
    perception = _g(s, "perception", "mod")
    perception = f"{perception:+d}" if isinstance(perception, int) else None
    speed = _g(s, "attributes", "speed", "value")
    hp = _g(s, "attributes", "hp", "max")
    if hp is None:
        hp = _g(s, "attributes", "hp", "value")
    return _pairs(
        ("Level", _g(s, "details", "level", "value")),
        ("Size", _g(s, "traits", "size", "value")),
        ("AC", _g(s, "attributes", "ac", "value")),
        ("HP", hp),
        ("Perception", perception),
        ("Saves", saves),
        ("Speed", f"{speed} feet" if speed is not None else None),
    )


def _spell(s: Mapping) -> tuple[tuple[str, str], ...]:
    area = _g(s, "area")
    area_str = None
    if isinstance(area, Mapping):
        if area.get("details"):
            area_str = area["details"]
        elif area.get("value") is not None:
            area_str = f"{area['value']}-foot {area.get('type') or ''}".strip()
    traditions = _g(s, "traits", "traditions")
    trad_str = ", ".join(traditions) if isinstance(traditions, list) and traditions else None
    return _pairs(
        ("Rank", _g(s, "level", "value")),
        ("Traditions", trad_str),
        ("Cast", _g(s, "time", "value")),
        ("Range", _g(s, "range", "value")),
        ("Area", area_str),
        ("Targets", _g(s, "target", "value")),
        ("Duration", _g(s, "duration", "value")),
        ("Defense", _g(s, "defense", "save", "statistic")),
    )


def _equipment(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Level", _g(s, "level", "value")),
        ("Price", _format_price(_g(s, "price", "value"))),
        ("Bulk", _g(s, "bulk", "value")),
        ("Usage", _g(s, "usage", "value")),
    )


def _feat(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Level", _g(s, "level", "value")),
        ("Activity", _activity(s)),
    )


def _action(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Activity", _activity(s)),
        ("Category", _g(s, "category")),
    )


def _hazard(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Level", _g(s, "details", "level", "value")),
        ("AC", _g(s, "attributes", "ac", "value")),
        ("HP", _g(s, "attributes", "hp", "value")),
        ("Stealth", _g(s, "attributes", "stealth", "value")),
    )


_EXTRACTORS = {
    "creature": _creature,
    "spell": _spell,
    "equipment": _equipment,
    "feat": _feat,
    "action": _action,
    "hazard": _hazard,
}


def extract_stats(category: str, system: Mapping) -> tuple[tuple[str, str], ...]:
    extractor = _EXTRACTORS.get(category)
    return extractor(system) if extractor else ()
