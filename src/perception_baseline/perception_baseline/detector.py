"""Детектор красных областей и проекция пикселя в точку без зависимостей от ROS."""

import json
from pathlib import Path

# причины, по которым пространственный результат неизвестен
MISSING_DEPTH = 'missing_depth'
ZERO_DEPTH = 'zero_depth'
STAMP_MISMATCH = 'stamp_mismatch'
FRAME_MISMATCH = 'frame_mismatch'
INVALID_DEPTH = 'invalid_depth'


def load_json(path):
    """Прочитать JSON-файл."""
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _netpbm_values(path, magic):
    tokens = []
    for line in Path(path).read_text(encoding='ascii').splitlines():
        tokens.extend(line.split('#', 1)[0].split())
    if len(tokens) < 4 or tokens[0] != magic:
        raise ValueError(f'ожидается {magic}: {path}')
    width, height, maximum = map(int, tokens[1:4])
    return width, height, maximum, [int(value) for value in tokens[4:]]


def load_ppm(path):
    """Прочитать текстовый PPM P3 и вернуть (width, height, [(r, g, b), ...])."""
    width, height, maximum, values = _netpbm_values(path, 'P3')
    if maximum != 255 or len(values) != width * height * 3:
        raise ValueError(f'неверный размер PPM: {path}')
    pixels = [tuple(values[i:i + 3]) for i in range(0, len(values), 3)]
    return width, height, pixels


def load_pgm(path):
    """Прочитать текстовый PGM P2 и вернуть (width, height, [value, ...])."""
    width, height, _, values = _netpbm_values(path, 'P2')
    if len(values) != width * height:
        raise ValueError(f'неверный размер PGM: {path}')
    return width, height, values


def detect_pixels(width, height, pixels, config):
    """Найти красные связные области, тот же алгоритм, что detect() в evaluator."""
    if config.get('channel_order') != 'rgb':
        raise ValueError('baseline принимает только RGB')
    red_min = int(config['red_min'])
    green_max = int(config['green_max'])
    blue_max = int(config['blue_max'])
    mask = {
        index
        for index, (red, green, blue) in enumerate(pixels)
        if red >= red_min and green <= green_max and blue <= blue_max
    }
    components = []
    while mask:
        stack = [mask.pop()]
        component = []
        while stack:
            index = stack.pop()
            component.append(index)
            x, y = index % width, index // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                neighbour = ny * width + nx
                if 0 <= nx < width and 0 <= ny < height and neighbour in mask:
                    mask.remove(neighbour)
                    stack.append(neighbour)
        if len(component) >= int(config['min_area_px']):
            components.append(component)
    boxes = []
    for component in components:
        xs = [index % width for index in component]
        ys = [index // width for index in component]
        boxes.append([min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1])
    return sorted(boxes)


def decode_rgb8(width, height, encoding, step, data):
    """Достать пиксели из байтов Image с учётом step."""
    data = bytes(data)
    if encoding != 'rgb8':
        raise ValueError(f'ожидается rgb8, получено {encoding}')
    if step < width * 3 or len(data) != step * height:
        raise ValueError('step и размер data не согласованы с width/height')
    return [
        tuple(data[y * step + x * 3:y * step + x * 3 + 3])
        for y in range(height)
        for x in range(width)
    ]


def decode_depth16(width, height, encoding, step, is_bigendian, data):
    """Достать глубину в миллиметрах из Image 16UC1 с учётом step и порядка байтов."""
    data = bytes(data)
    if encoding != '16UC1':
        raise ValueError(f'ожидается 16UC1, получено {encoding}')
    if step < width * 2 or len(data) != step * height:
        raise ValueError('step и размер data не согласованы с width/height')
    order = 'big' if is_bigendian else 'little'
    return [
        int.from_bytes(data[y * step + x * 2:y * step + x * 2 + 2], order)
        for y in range(height)
        for x in range(width)
    ]


def depth_pixel(bbox):
    """Пиксель (u, v), глубину которого берём для bbox [x, y, w, h]."""
    x, y, width, height = bbox
    return x + width // 2, y + height // 2


def project(u, v, raw_depth, calibration):
    """Точка (X, Y, Z) в camera_optical_frame для пикселя и сырой глубины."""
    z = raw_depth * calibration['depth_scale_m']
    x = (u - calibration['cx']) * z / calibration['fx']
    y = (v - calibration['cy']) * z / calibration['fy']
    return x, y, z


def encode_rgb8(pixels):
    """Упаковать пиксели в байты rgb8 без выравнивания строк."""
    return bytes(channel for pixel in pixels for channel in pixel)


def encode_depth16(values, is_bigendian=False):
    """Упаковать глубину в байты 16UC1."""
    order = 'big' if is_bigendian else 'little'
    return b''.join(int(value).to_bytes(2, order) for value in values)
