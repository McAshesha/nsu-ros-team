"""Ключ кэша VLM и хранилище сырых ответов."""

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def cache_key(image_sha256, prompt_sha256, model_id, generation_config,
              schema_version=SCHEMA_VERSION):
    """SHA-256 от канонического JSON всех входов, влияющих на ответ модели."""
    payload = {
        'image_sha256': image_sha256,
        'prompt_sha256': prompt_sha256,
        'model_id': model_id,
        'generation_config': generation_config,
        'schema_version': schema_version,
    }
    text = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class ResponseCache:

    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, key):
        return self.directory / f'{key}.json'

    def get(self, key):
        path = self.path(key)
        return path.read_text(encoding='utf-8') if path.is_file() else None

    def put(self, key, raw_text):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path(key).write_text(raw_text, encoding='utf-8')
