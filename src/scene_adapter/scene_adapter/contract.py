"""Контракт SceneDescription v1: проверка ответа, канонический unknown и JSON <-> ROS."""

import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator
from robotics_course_interfaces.msg import SceneDescription

INVALID_SCHEMA = 'invalid_schema'
LOW_CONFIDENCE = 'low_confidence'
STALE_INPUT = 'stale_input'

LIGHTS = {
    'none': SceneDescription.LIGHT_NONE,
    'red': SceneDescription.LIGHT_RED,
    'yellow': SceneDescription.LIGHT_YELLOW,
    'green': SceneDescription.LIGHT_GREEN,
    'unknown': SceneDescription.LIGHT_UNKNOWN,
}
SIGNS = {
    'none': SceneDescription.SIGN_NONE,
    'left': SceneDescription.SIGN_LEFT,
    'right': SceneDescription.SIGN_RIGHT,
    'straight': SceneDescription.SIGN_STRAIGHT,
    'unknown': SceneDescription.SIGN_UNKNOWN,
}
STATUSES = {'valid': SceneDescription.STATUS_VALID, 'unknown': SceneDescription.STATUS_UNKNOWN}
DISTANCES = ('stop_line', 'turn', 'obstacle')


def load_validator(schema_path):
    schema = json.loads(Path(schema_path).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(validator, scene):
    return [error.message for error in validator.iter_errors(scene)]


def unknown_scene(reason, source, stamp_s=0.0, frame_id='base_link'):
    """Канонический unknown: категории unknown, расстояния null, confidence 0."""
    return {
        'version': 1,
        'stamp_s': stamp_s,
        'frame_id': frame_id,
        'status': 'unknown',
        'status_reason': reason,
        'lane_offset_m': 0.0,
        'traffic_light': 'unknown',
        'direction_sign': 'unknown',
        'stop_line_distance_m': None,
        'turn_distance_m': None,
        'obstacle_distance_m': None,
        'confidence': 0.0,
        'source': source,
    }


def _origin(raw):
    """Метка и frame исходного наблюдения, если они допустимы."""
    stamp, frame = 0.0, 'base_link'
    if isinstance(raw, dict):
        value = raw.get('stamp_s')
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value) and value >= 0:
            stamp = float(value)
        if isinstance(raw.get('frame_id'), str) and raw['frame_id']:
            frame = raw['frame_id']
    return stamp, frame


def evaluate(raw_text, now_s, validator, abstain_threshold, max_age_s, source):
    """Проверить сырой ответ и вернуть сцену: valid или канонический unknown."""
    try:
        raw = json.loads(raw_text)
    except (TypeError, ValueError):
        return unknown_scene(INVALID_SCHEMA, source)
    stamp, frame = _origin(raw)
    # управляющее или любое лишнее поле отклоняет весь ответ (additionalProperties)
    if not isinstance(raw, dict) or schema_errors(validator, raw):
        return unknown_scene(INVALID_SCHEMA, source, stamp, frame)
    if raw['status'] == 'unknown':
        return dict(raw, source=source)
    age = now_s - raw['stamp_s']
    if not 0.0 <= age <= max_age_s:
        return unknown_scene(STALE_INPUT, source, stamp, frame)
    if raw['confidence'] < abstain_threshold:
        return unknown_scene(LOW_CONFIDENCE, source, stamp, frame)
    return dict(raw, source=source)


def to_msg(scene):
    """Перевести JSON-сцену в SceneDescription по таблице контракта."""
    msg = SceneDescription()
    sec = math.floor(scene['stamp_s'])
    nanosec = round((scene['stamp_s'] - sec) * 1e9)
    if nanosec >= 1_000_000_000:
        sec, nanosec = sec + 1, nanosec - 1_000_000_000
    msg.header.stamp.sec, msg.header.stamp.nanosec = int(sec), int(nanosec)
    msg.header.frame_id = scene['frame_id']
    msg.version = scene['version']
    msg.status = STATUSES[scene['status']]
    msg.status_reason = scene['status_reason']
    msg.traffic_light = LIGHTS[scene['traffic_light']]
    msg.direction_sign = SIGNS[scene['direction_sign']]
    msg.lane_offset_m = float(scene['lane_offset_m'])
    for name in DISTANCES:
        value = scene[f'{name}_distance_m']
        setattr(msg, f'has_{name}', value is not None)
        setattr(msg, f'{name}_distance_m', 0.0 if value is None else float(value))
    msg.confidence = float(scene['confidence'])
    msg.source = scene['source']
    return msg


def from_msg(msg):
    """Перевести SceneDescription в JSON-сцену; has_* = false становится null."""
    lights = {value: key for key, value in LIGHTS.items()}
    signs = {value: key for key, value in SIGNS.items()}
    statuses = {value: key for key, value in STATUSES.items()}
    scene = {
        'version': msg.version,
        'stamp_s': msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9,
        'frame_id': msg.header.frame_id,
        'status': statuses[msg.status],
        'status_reason': msg.status_reason,
        'lane_offset_m': msg.lane_offset_m,
        'traffic_light': lights[msg.traffic_light],
        'direction_sign': signs[msg.direction_sign],
        'confidence': msg.confidence,
        'source': msg.source,
    }
    for name in DISTANCES:
        has = getattr(msg, f'has_{name}')
        scene[f'{name}_distance_m'] = getattr(msg, f'{name}_distance_m') if has else None
    return scene


def scene_to_msg(scene, validator):
    """Последняя проверка перед публикацией: неизвестный enum даёт unknown."""
    try:
        if schema_errors(validator, scene):
            raise KeyError('scene не соответствует схеме')
        return to_msg(scene)
    except KeyError:
        stamp, frame = _origin(scene)
        return to_msg(unknown_scene(INVALID_SCHEMA, scene.get('source', 'mock'), stamp, frame))
