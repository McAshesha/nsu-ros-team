"""Поиск course kit для тестов: каталог .course-kit в корне репозитория."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def kit_dir():
    for parent in Path(__file__).resolve().parents:
        candidate = parent / '.course-kit' / 'v1'
        if candidate.is_dir():
            return candidate
    return None


KIT = kit_dir()
FIXTURE = KIT / 'fixtures' / 'pr09' if KIT else None
