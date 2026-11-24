import importlib.util

from kit import FIXTURE, KIT, PACKAGE
from perception_baseline import detector
import pytest

needs_kit = pytest.mark.skipif(KIT is None, reason='нет .course-kit/v1 в корне репозитория')
SAMPLES = [f'sample-0{n}' for n in range(1, 7)]
CALIBRATION = {'fx': 8.0, 'fy': 8.0, 'cx': 3.5, 'cy': 2.5, 'depth_scale_m': 0.001}


def load_evaluator():
    spec = importlib.util.spec_from_file_location(
        'evaluate_perception', KIT / 'tools' / 'evaluate_perception.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_kit
def test_configs_are_unchanged_copies_of_fixture():
    for name in ('baseline-detector.json', 'calibration.json'):
        assert (PACKAGE / 'config' / name).read_bytes() == (FIXTURE / name).read_bytes()


@needs_kit
@pytest.mark.parametrize('sample', SAMPLES)
def test_detector_matches_public_evaluator(sample):
    evaluator = load_evaluator()
    config = detector.load_json(FIXTURE / 'baseline-detector.json')
    image = FIXTURE / 'images' / f'{sample}.ppm'
    width, height, pixels = detector.load_ppm(image)
    assert detector.detect_pixels(width, height, pixels, config) == evaluator.detect(image, config)


@needs_kit
def test_bytes_roundtrip_gives_same_detections():
    config = detector.load_json(FIXTURE / 'baseline-detector.json')
    width, height, pixels = detector.load_ppm(FIXTURE / 'images' / 'sample-06.ppm')
    decoded = detector.decode_rgb8(width, height, 'rgb8', width * 3, detector.encode_rgb8(pixels))
    assert detector.detect_pixels(width, height, decoded, config) == [[0, 0, 1, 2], [4, 3, 2, 2]]


def test_depth_pixel_is_bbox_center_rounded_down():
    assert detector.depth_pixel([4, 1, 2, 3]) == (5, 2)
    assert detector.depth_pixel([1, 1, 3, 2]) == (2, 2)


def test_projection_matches_formula():
    x, y, z = detector.project(5, 2, 1000, CALIBRATION)
    assert (x, y, z) == pytest.approx((0.1875, -0.0625, 1.0))


def test_rgb_step_with_row_padding():
    data = bytes([1, 2, 3, 4, 5, 6, 0, 0, 7, 8, 9, 10, 11, 12, 0, 0])
    assert detector.decode_rgb8(2, 2, 'rgb8', 8, data) == [
        (1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]


def test_depth_byte_order():
    big = detector.encode_depth16([1000, 2], is_bigendian=True)
    assert detector.decode_depth16(2, 1, '16UC1', 4, True, big) == [1000, 2]
    little = detector.encode_depth16([1000, 2])
    assert detector.decode_depth16(2, 1, '16UC1', 4, False, little) == [1000, 2]


@pytest.mark.parametrize('encoding, step, size', [('32FC1', 16, 16), ('16UC1', 8, 15)])
def test_invalid_depth_is_rejected(encoding, step, size):
    with pytest.raises(ValueError):
        detector.decode_depth16(8, 2, encoding, step, False, bytes(size))
