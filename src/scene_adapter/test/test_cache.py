import json

from no_network import no_network  # noqa: F401
from paths import FIXTURES, PROMPT, SCHEMA
import pytest
from scene_adapter import contract
from scene_adapter.adapter import SceneAdapter
from scene_adapter.cache import cache_key, sha256_bytes

IMAGE = b'frame-1'
CONFIG = {'max_tokens': 512, 'temperature': 0.0}


class CountingBackend:
    """Локальный backend без сети: отдаёт заданный сырой ответ и считает вызовы."""

    def __init__(self, raw):
        self.raw = raw
        self.calls = 0

    def __call__(self, image_bytes, prompt, model_id, generation_config):
        self.calls += 1
        return self.raw


def raw_scene(**changes):
    scene = json.loads((FIXTURES / 'scene-clear.json').read_text(encoding='utf-8'))
    scene.update(changes)
    return json.dumps(scene)


@pytest.fixture
def setup(tmp_path):
    prompt = tmp_path / 'prompt.txt'
    prompt.write_bytes(PROMPT.read_bytes())
    backend = CountingBackend(raw_scene(traffic_light='green'))
    adapter = SceneAdapter('cache', contract.load_validator(SCHEMA), 0.5, 0.25,
                           cache_dir=tmp_path / 'cache', prompt_path=prompt,
                           model_id='Qwen3.8-27B', generation_config=dict(CONFIG),
                           backend=backend)
    return adapter, backend, prompt


def test_miss_calls_backend_and_hit_does_not(setup):
    adapter, backend, _ = setup
    first = adapter.describe(0.1, IMAGE)
    second = adapter.describe(0.1, IMAGE)
    assert backend.calls == 1
    assert first == second
    assert first['status'] == 'valid' and first['source'] == 'cache'


def test_cache_hit_is_checked_for_age_again(setup):
    adapter, backend, _ = setup
    assert adapter.describe(0.1, IMAGE)['status'] == 'valid'
    stale = adapter.describe(2.0, IMAGE)
    assert backend.calls == 1
    assert (stale['status'], stale['status_reason']) == ('unknown', contract.STALE_INPUT)


def change_and_describe(adapter, backend, prompt, component):
    """Изменить один вход ключа; backend теперь отвечает другой сценой."""
    image = IMAGE
    if component == 'image':
        image = b'frame-2'
    elif component == 'prompt':
        prompt.write_text(prompt.read_text(encoding='utf-8') + '\nUse metric units.\n',
                          encoding='utf-8')
    elif component == 'model_id':
        adapter.model_id = 'another-model'
    elif component == 'generation_config':
        adapter.generation_config = dict(CONFIG, temperature=0.7)
    backend.raw = raw_scene(traffic_light='red')
    return adapter.describe(0.1, image)


@pytest.mark.parametrize('component', ['image', 'prompt', 'model_id', 'generation_config'])
def test_each_input_change_is_cache_miss(setup, component):
    adapter, backend, prompt = setup
    assert adapter.describe(0.1, IMAGE)['traffic_light'] == 'green'
    scene = change_and_describe(adapter, backend, prompt, component)
    # при коллизии ключа вернулась бы старая сцена с зелёным светом
    assert backend.calls == 2, f'изменение {component} не дало промаха кэша'
    assert scene['traffic_light'] == 'red'


@pytest.mark.parametrize('field, value', [
    ('image_sha256', sha256_bytes(b'frame-2')),
    ('prompt_sha256', sha256_bytes(b'other prompt')),
    ('model_id', 'another-model'),
    ('generation_config', dict(CONFIG, temperature=0.7)),
    ('schema_version', 2),
])
def test_each_key_component_changes_key(field, value):
    base = {'image_sha256': sha256_bytes(IMAGE), 'prompt_sha256': sha256_bytes(b'prompt'),
            'model_id': 'Qwen3.8-27B', 'generation_config': dict(CONFIG), 'schema_version': 1}
    changed = dict(base, **{field: value})
    assert cache_key(**base) != cache_key(**changed)


def test_key_does_not_depend_on_config_key_order():
    a = cache_key('i', 'p', 'm', {'temperature': 0.0, 'max_tokens': 512})
    b = cache_key('i', 'p', 'm', {'max_tokens': 512, 'temperature': 0.0})
    assert a == b


def test_live_without_backend_fails_clearly():
    with pytest.raises(RuntimeError, match='backend'):
        SceneAdapter('live', contract.load_validator(SCHEMA), 0.5, 0.25)


def test_cache_miss_without_backend_fails_clearly(tmp_path):
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('p', encoding='utf-8')
    adapter = SceneAdapter('cache', contract.load_validator(SCHEMA), 0.5, 0.25,
                           cache_dir=tmp_path / 'cache', prompt_path=prompt)
    with pytest.raises(RuntimeError, match='backend'):
        adapter.describe(0.1, IMAGE)
