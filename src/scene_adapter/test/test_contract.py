import json

from no_network import no_network  # noqa: F401
from paths import FIXTURES, SCHEMA
import pytest
from robotics_course_interfaces.msg import SceneDescription
from scene_adapter import contract
from scene_adapter.adapter import SceneAdapter

THRESHOLD = 0.5
MAX_AGE = 0.25
# fixture, now_s, ожидаемый status, ожидаемая причина (fixtures/vlm/README.md)
CASES = [
    ('scene-clear.json', 0.1, 'valid', ''),
    ('scene-low-confidence.json', 0.1, 'unknown', contract.LOW_CONFIDENCE),
    ('scene-stale.json', 2.0, 'unknown', contract.STALE_INPUT),
    ('scene-extra-command.json', 0.1, 'unknown', contract.INVALID_SCHEMA),
]


@pytest.fixture(scope='module')
def validator():
    return contract.load_validator(SCHEMA)


def mock(validator, name):
    return SceneAdapter('mock', validator, THRESHOLD, MAX_AGE, fixture_path=FIXTURES / name)


@pytest.mark.parametrize('name, now_s, status, reason', CASES)
def test_fixture_gives_expected_result(validator, name, now_s, status, reason):
    scene = mock(validator, name).describe(now_s)
    assert scene['status'] == status
    assert scene['status_reason'] == reason
    assert contract.schema_errors(validator, scene) == []


@pytest.mark.parametrize('name, now_s, status, reason', CASES[1:])
def test_unknown_is_canonical_and_keeps_origin(validator, name, now_s, status, reason):
    raw = json.loads((FIXTURES / name).read_text(encoding='utf-8'))
    scene = mock(validator, name).describe(now_s)
    assert scene['traffic_light'] == 'unknown' and scene['direction_sign'] == 'unknown'
    assert [scene[f'{n}_distance_m'] for n in contract.DISTANCES] == [None, None, None]
    assert scene['confidence'] == 0
    assert (scene['stamp_s'], scene['frame_id']) == (raw['stamp_s'], raw['frame_id'])


def test_drive_field_rejects_whole_answer(validator):
    scene = mock(validator, 'scene-extra-command.json').describe(0.1)
    assert 'drive' not in scene
    assert scene['lane_offset_m'] == 0.0 and scene['traffic_light'] == 'unknown'


def test_clear_scene_is_unchanged_except_source(validator):
    raw = json.loads((FIXTURES / 'scene-clear.json').read_text(encoding='utf-8'))
    assert mock(validator, 'scene-clear.json').describe(0.1) == raw


@pytest.mark.parametrize('text', ['not json', '[]', '{"version": 1}'])
def test_broken_answer_is_invalid_schema(validator, text):
    scene = contract.evaluate(text, 0.1, validator, THRESHOLD, MAX_AGE, 'cache')
    assert (scene['status'], scene['status_reason']) == ('unknown', contract.INVALID_SCHEMA)


def roundtrip(scene):
    return contract.from_msg(contract.to_msg(scene))


def assert_same(a, b):
    assert a.keys() == b.keys()
    for key in a:
        if isinstance(a[key], float) or isinstance(b[key], float):
            assert a[key] == pytest.approx(b[key], abs=1e-6), key
        else:
            assert a[key] == b[key], key


@pytest.mark.parametrize('light', list(contract.LIGHTS))
@pytest.mark.parametrize('sign', list(contract.SIGNS))
def test_roundtrip_all_enums(validator, light, sign):
    scene = json.loads((FIXTURES / 'scene-clear.json').read_text(encoding='utf-8'))
    scene.update(traffic_light=light, direction_sign=sign)
    assert_same(roundtrip(scene), scene)


def test_roundtrip_null_distances(validator):
    scene = contract.unknown_scene(contract.STALE_INPUT, 'mock', 1.0, 'base_link')
    msg = contract.to_msg(scene)
    assert (msg.has_stop_line, msg.has_turn, msg.has_obstacle) == (False, False, False)
    assert msg.stop_line_distance_m == 0.0
    assert msg.traffic_light == SceneDescription.LIGHT_UNKNOWN
    assert_same(contract.from_msg(msg), scene)


@pytest.mark.parametrize('stamp_s, sec, nanosec', [
    (0.0, 0, 0), (1.0, 1, 0), (1.5, 1, 500_000_000),
    (12.123456789, 12, 123_456_789), (2.9999999999, 3, 0)])
def test_stamp_conversion(stamp_s, sec, nanosec):
    scene = contract.unknown_scene(contract.STALE_INPUT, 'mock', stamp_s)
    msg = contract.to_msg(scene)
    assert (msg.header.stamp.sec, msg.header.stamp.nanosec) == (sec, nanosec)
    assert contract.from_msg(msg)['stamp_s'] == pytest.approx(stamp_s, abs=1e-6)


def test_unknown_enum_becomes_invalid_schema(validator):
    scene = json.loads((FIXTURES / 'scene-clear.json').read_text(encoding='utf-8'))
    scene['traffic_light'] = 'blue'
    msg = contract.scene_to_msg(scene, validator)
    assert msg.status == SceneDescription.STATUS_UNKNOWN
    assert msg.status_reason == contract.INVALID_SCHEMA
