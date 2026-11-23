"""Пути к копиям контракта и fixtures в корне репозитория."""

from pathlib import Path


def repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / 'contracts' / 'scene-description-v1.schema.json').is_file():
            return parent
    raise FileNotFoundError('не найден contracts/scene-description-v1.schema.json')


ROOT = repo_root()
SCHEMA = ROOT / 'contracts' / 'scene-description-v1.schema.json'
FIXTURES = ROOT / 'fixtures' / 'vlm'
PROMPT = ROOT / 'config' / 'scene-prompt.txt'
