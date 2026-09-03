"""Loads the vertical configuration (config/vertical/<name>/). The engine reads
domain knowledge ONLY through this module; nothing in app/ hardcodes a vertical."""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings


@dataclass(frozen=True)
class RoleFamily:
    key: str
    band: str
    label: str
    title_synonyms: tuple[str, ...]
    signals: dict
    typical_background: str
    qualifying_degree_fields: tuple[str, ...]


@dataclass(frozen=True)
class Skill:
    canonical: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Vertical:
    name: str
    bands: dict  # band_key -> {label, description, default_ai_relevance}
    families: dict  # family_key -> RoleFamily
    ai_relevance_levels: dict
    dashboard_default_ai_relevance: tuple[str, ...]
    skills: tuple[Skill, ...]
    _alias_index: dict = field(default_factory=dict, repr=False)

    def families_in_band(self, band: str) -> list[RoleFamily]:
        return [f for f in self.families.values() if f.band == band]

    def normalize_skill(self, raw: str) -> Skill | None:
        return self._alias_index.get(_norm(raw))

    def normalize_skills(self, raws: list[str]) -> tuple[list[str], list[str]]:
        """Return (canonical skills, unmatched raw skills); both de-duplicated, order kept."""
        canonical: list[str] = []
        other: list[str] = []
        for raw in raws:
            if not raw or not raw.strip():
                continue
            hit = self.normalize_skill(raw)
            if hit and hit.canonical not in canonical:
                canonical.append(hit.canonical)
            elif not hit and raw.strip() not in other:
                other.append(raw.strip())
        return canonical, other


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("_", " ").split())


def vertical_dir(name: str | None = None) -> Path:
    root = Path(get_settings().vertical_config_dir)
    return root / (name or get_settings().vertical)


@lru_cache
def load_vertical(name: str | None = None) -> Vertical:
    base = vertical_dir(name)
    rf = yaml.safe_load((base / "role_families.yaml").read_text())
    tx = yaml.safe_load((base / "skills_taxonomy.yaml").read_text())

    families = {}
    for key, cfg in rf["families"].items():
        if cfg["band"] not in rf["bands"]:
            raise ValueError(f"role family '{key}' references unknown band '{cfg['band']}'")
        families[key] = RoleFamily(
            key=key,
            band=cfg["band"],
            label=cfg["label"],
            title_synonyms=tuple(_norm(s) for s in cfg.get("title_synonyms", [])),
            signals=dict(cfg.get("signals", {})),
            typical_background=cfg.get("typical_background", ""),
            qualifying_degree_fields=tuple(_norm(d) for d in cfg.get("qualifying_degree_fields", [])),
        )

    skills: list[Skill] = []
    alias_index: dict[str, Skill] = {}
    for category, entries in tx["categories"].items():
        for e in entries:
            skill = Skill(canonical=e["canonical"], category=category,
                          aliases=tuple(e.get("aliases", [])))
            skills.append(skill)
            for name_ in (skill.canonical, *skill.aliases):
                alias_index.setdefault(_norm(name_), skill)

    return Vertical(
        name=rf.get("vertical", name or get_settings().vertical),
        bands=rf["bands"],
        families=families,
        ai_relevance_levels=rf["ai_relevance_levels"],
        dashboard_default_ai_relevance=tuple(rf.get("dashboard_default_ai_relevance", [])),
        skills=tuple(skills),
        _alias_index=alias_index,
    )
