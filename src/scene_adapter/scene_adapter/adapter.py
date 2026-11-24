"""Адаптер VLM без ROS: режимы mock, cache и live."""

import json
from pathlib import Path

from scene_adapter import contract
from scene_adapter.cache import cache_key, ResponseCache, SCHEMA_VERSION, sha256_bytes

MODES = ('mock', 'cache', 'live')


class SceneAdapter:
    """Возвращает сцену SceneDescription v1 в виде dict."""

    def __init__(self, mode, validator, abstain_threshold, max_age_s, fixture_path='',
                 cache_dir='', prompt_path='', model_id='', generation_config=None,
                 backend=None):
        if mode not in MODES:
            raise ValueError(f'mode должен быть одним из {MODES}, получено {mode!r}')
        if mode == 'live' and backend is None:
            # сетевой клиент не создаётся сам по себе
            raise RuntimeError('режим live требует явно настроенного backend')
        self.mode = mode
        self.validator = validator
        self.abstain_threshold = abstain_threshold
        self.max_age_s = max_age_s
        self.fixture_path = fixture_path
        self.cache = ResponseCache(cache_dir) if cache_dir else None
        self.prompt_path = prompt_path
        self.model_id = model_id
        self.generation_config = generation_config or {}
        self.backend = backend

    def key_for(self, image_bytes):
        prompt = Path(self.prompt_path).read_bytes()
        return cache_key(sha256_bytes(image_bytes), sha256_bytes(prompt), self.model_id,
                         self.generation_config, SCHEMA_VERSION)

    def raw_response(self, image_bytes):
        if self.mode == 'mock':
            return Path(self.fixture_path).read_text(encoding='utf-8')
        prompt = Path(self.prompt_path).read_text(encoding='utf-8')
        if self.mode == 'live':
            return self.backend(image_bytes, prompt, self.model_id, self.generation_config)
        key = self.key_for(image_bytes)
        raw = self.cache.get(key)
        if raw is None:
            if self.backend is None:
                raise RuntimeError('промах кэша, а backend не настроен')
            raw = self.backend(image_bytes, prompt, self.model_id, self.generation_config)
            self.cache.put(key, raw)
        return raw

    def describe(self, now_s, image_bytes=b''):
        raw = self.raw_response(image_bytes)
        return contract.evaluate(raw, now_s, self.validator, self.abstain_threshold,
                                 self.max_age_s, self.mode)


def fixture_backend(path):
    """Локальный backend: возвращает сохранённый сырой ответ из файла, без сети."""
    def backend(image_bytes, prompt, model_id, generation_config):
        return Path(path).read_text(encoding='utf-8')
    return backend


def parse_config(text):
    value = json.loads(text) if text else {}
    if not isinstance(value, dict):
        raise ValueError('generation_config должен быть JSON-объектом')
    return value
