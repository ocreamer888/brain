"""High-confidence project inference from memory content.

Used to retag Cursor path-fragment projects (cursor/src/frontend/…) onto
canonical product names when the content itself names the project.
Only unique matches are safe to apply — ambiguous / empty → None.
"""
from __future__ import annotations

import re
from pathlib import Path

# Longer aliases first so "sicop-health" wins over "sicop".
_ALIAS_PAIRS: list[tuple[str, str]] = [
    ("sicop-health", "sicop-health"),
    ("sicop health", "sicop-health"),
    ("qol-clinics", "qol-clinics"),
    ("qol clinics", "qol-clinics"),
    ("le_chandelier", "le_chandelier"),
    ("le-chandelier", "le_chandelier"),
    ("le chandelier", "le_chandelier"),
    ("lechandelier", "le_chandelier"),
    ("farmaplus", "farmaplus"),
    ("farma plus", "farmaplus"),
    ("farma-plus", "farmaplus"),
    ("med-defi", "meddefi"),
    ("meddefi", "meddefi"),
    ("wealthcare", "wealth"),
    ("flywithus", "flywithus"),
    ("fly with us", "flywithus"),
    ("ocreamerstudio", "ocreamer"),
    ("ocreamer", "ocreamer"),
    ("owelign", "owelign"),
    ("sakbé", "owelign"),
    ("sakbe", "owelign"),
    ("tilopay", "tilopay"),
    ("natuvia", "natuvia"),
    ("lifehub", "lifehub"),
    ("synapses", "lifehub"),
    ("hackathon-workshop", "hackathon-workshop"),
    ("obsidian-brain", "obsidian-brain"),
    ("brain_api", "brain"),
    ("brain.db", "brain"),
    ("documents/code/brain", "brain"),
    ("documents/ai/brain", "brain"),
    ("/documents/ai", "AI"),
    ("documents/ai ", "AI"),  # trailing space avoids matching AI/brain paths only partially
    ("sicop", "sicop"),
    ("tayasal", "tayasal"),
    ("inventario", "inventario"),
    ("ppf-contact", "ppf"),
    ("ppf", "ppf"),
    ("rmt", "rmt"),
]

# Absolute path: …/Documents/<name>/ or …/Code/<name>/
_ABS_PROJECT_RE = re.compile(
    r"/(?:Users|Shared)/(?:[^/\s]+/)*(?:Documents|Code)/([^/\s\"'`]+)",
    re.IGNORECASE,
)

# Skip path segments that are path-fragments themselves
_SKIP_PATH_PARTS = frozenset({
    "cursor", "src", "frontend", "landingpage", "app", "lib", "components",
    "pages", "utils", "hooks", "rust", "test", "etl", ".claude", "Code",
    "Documents", "Users", "Shared", "macm1air", "abundancia888",
})

# Map folder names → canonical (from session_start PROJECT_DIR_MAP + extras)
_FOLDER_MAP = {
    "lifehub": "lifehub",
    "LifeHub": "lifehub",
    "wealth": "wealth",
    "Wealth": "wealth",
    "le-chandelier": "le_chandelier",
    "lechandelier": "le_chandelier",
    "le chandelier-restaurant": "le_chandelier",
    "meddefi": "meddefi",
    "MedDeFi": "meddefi",
    "ocreamer": "ocreamer",
    "OCREAMER": "ocreamer",
    "ocreamerstudio": "ocreamer",
    "owelign": "owelign",
    "OWELIGN": "owelign",
    "qol": "qol",
    "qol-clinics": "qol-clinics",
    "rmt": "rmt",
    "sicop": "sicop",
    "sicop-health": "sicop-health",
    "tayasal": "tayasal",
    "scheduler": "scheduler",
    "inventario": "inventario",
    "AI": "AI",
    "brain": "brain",
    "farmaplus": "farmaplus",
    "FarmaPlus": "farmaplus",
    "flywithus": "flywithus",
    "tilopay": "tilopay",
}


def infer_projects(content: str) -> set[str]:
    """Return all canonical projects hinted by content (may be empty or many)."""
    text = content or ""
    lower = text.lower()
    found: set[str] = set()

    for alias, canon in _ALIAS_PAIRS:
        if alias.lower() in lower:
            found.add(canon)

    for m in _ABS_PROJECT_RE.finditer(text):
        part = m.group(1)
        if part in _SKIP_PATH_PARTS:
            continue
        if part in _FOLDER_MAP:
            found.add(_FOLDER_MAP[part])
        else:
            for k, v in _FOLDER_MAP.items():
                if k.lower() == part.lower():
                    found.add(v)
                    break

    # Prefer specific over parent when both fire (sicop ⊂ sicop-health)
    if "sicop-health" in found:
        found.discard("sicop")
    if "qol-clinics" in found:
        found.discard("qol")

    return found


def infer_unique_project(content: str) -> str | None:
    """Return canonical project iff exactly one project is inferred."""
    found = infer_projects(content)
    if len(found) == 1:
        return next(iter(found))
    return None


def is_path_fragment_project(project: str) -> bool:
    return project in _SKIP_PATH_PARTS or project in {
        "cursor", "src", "frontend", "landingpage", ".claude", "rust", "test", "etl",
    }
