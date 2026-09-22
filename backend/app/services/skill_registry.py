"""Controlled, read-only Grade 8 algebra skill registry."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


UNKNOWN_SKILL_CODE = "unknown"
_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "grade8_algebra_skill_taxonomy_v1.json"


def _normalize(label: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", label).casefold().split())


@dataclass(frozen=True)
class SkillDefinition:
    code: str
    name_vi: str
    subject: str
    grade_min: int
    grade_max: int
    prerequisites: tuple[str, ...]
    aliases: tuple[str, ...]
    observable_mastery_evidence: tuple[str, ...]
    common_misconceptions: tuple[str, ...]
    verifier_family: str


@dataclass(frozen=True)
class SkillRegistry:
    skills: tuple[SkillDefinition, ...]
    _lookup: Mapping[str, str]
    _codes: frozenset[str]

    def resolve(self, label: str) -> str:
        if not isinstance(label, str):
            return UNKNOWN_SKILL_CODE
        return self._lookup.get(_normalize(label), UNKNOWN_SKILL_CODE)

    def is_mastery_bearing(self, code: str) -> bool:
        return code in self._codes


def _build_registry(data: dict) -> SkillRegistry:
    """Validate parsed taxonomy data and build an immutable lookup."""
    records = data["skills"]
    reserved = {_normalize(label) for label in data["reserved_non_mastery_labels"]}
    if not isinstance(records, list) or not records:
        raise ValueError("Taxonomy must contain skills")

    skills: list[SkillDefinition] = []
    codes: set[str] = set()
    lookup: dict[str, str] = {}

    for record in records:
        code = record["code"]
        if not isinstance(code, str) or not code.strip() or code != code.strip():
            raise ValueError("Skill code must be a non-empty canonical string")
        normalized_code = _normalize(code)
        if code in codes or normalized_code in lookup:
            raise ValueError(f"Duplicate skill code: {code}")
        if normalized_code in reserved or normalized_code == UNKNOWN_SKILL_CODE:
            raise ValueError(f"Reserved label cannot be a skill code: {code}")
        codes.add(code)
        lookup[normalized_code] = code
        skills.append(
            SkillDefinition(
                code=code,
                name_vi=record["name_vi"],
                subject=record["subject"],
                grade_min=record["grade_min"],
                grade_max=record["grade_max"],
                prerequisites=tuple(record["prerequisites"]),
                aliases=tuple(record["aliases"]),
                observable_mastery_evidence=tuple(record["observable_mastery_evidence"]),
                common_misconceptions=tuple(record["common_misconceptions"]),
                verifier_family=record["verifier_family"],
            )
        )

    for skill in skills:
        for label in skill.aliases:
            normalized = _normalize(label)
            if not normalized or normalized in reserved or normalized == UNKNOWN_SKILL_CODE:
                raise ValueError(f"Invalid alias for {skill.code}: {label}")
            existing = lookup.get(normalized)
            if existing is not None and existing != skill.code:
                raise ValueError(f"Alias collision: {label}")
            lookup[normalized] = skill.code
        for prerequisite in skill.prerequisites:
            if prerequisite not in codes:
                raise ValueError(f"Missing prerequisite {prerequisite} for {skill.code}")

    prerequisites_by_code = {skill.code: skill.prerequisites for skill in skills}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(code: str) -> None:
        if code in visiting:
            raise ValueError(f"Prerequisite cycle at {code}")
        if code in visited:
            return
        visiting.add(code)
        for prerequisite in prerequisites_by_code[code]:
            visit(prerequisite)
        visiting.remove(code)
        visited.add(code)

    for code in codes:
        visit(code)

    return SkillRegistry(tuple(skills), MappingProxyType(lookup), frozenset(codes))


with _TAXONOMY_PATH.open(encoding="utf-8") as taxonomy_file:
    _REGISTRY = _build_registry(json.load(taxonomy_file))


def get_controlled_skills() -> tuple[SkillDefinition, ...]:
    return _REGISTRY.skills


def get_skill_definition(code: str) -> SkillDefinition | None:
    for skill in _REGISTRY.skills:
        if skill.code == code:
            return skill
    return None


def get_direct_prerequisites(code: str) -> tuple[str, ...]:
    skill = get_skill_definition(code)
    return skill.prerequisites if skill is not None else ()


def get_direct_dependents(code: str) -> tuple[str, ...]:
    return tuple(
        skill.code
        for skill in _REGISTRY.skills
        if code in skill.prerequisites
    )


def resolve_skill_code(label: str) -> str:
    return _REGISTRY.resolve(label)


def is_mastery_bearing_skill(code: str) -> bool:
    return _REGISTRY.is_mastery_bearing(code)
