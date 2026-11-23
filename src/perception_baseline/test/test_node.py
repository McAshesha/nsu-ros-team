import os
import time

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from kit import FIXTURE, KIT, PACKAGE
from perception_baseline import detector
from perception_baseline.perception_node import PerceptionNode
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray, Detection3DArray

pytestmark = pytest.mark.skipif(KIT is None, reason='нет .course-kit/v1 в корне репозитория')

FRAME = 'camera_optical_frame'
# светлый объект, который baseline находит: bbox [4, 1, 2, 3], пиксель (5, 2)
SAMPLE = 'sample-04'


@pytest.fixture(scope='module', autouse=True)
def ros():
    # отдельный домен, чтобы тесты не пересекались с ручным показом
    os.environ['ROS_DOMAIN_ID'] = '71'
    rclpy.init()
    yield
    rclpy.try_shutdown()


class Harness:

    def __init__(self):
        self.node = rclpy.create_node('perception_test')
        self.perception = PerceptionNode(parameter_overrides=[
            Parameter('detector_config', value=str(PACKAGE / 'config' / 'baseline-detector.json')),
            Parameter('calibration', value=str(PACKAGE / 'config' / 'calibration.json')),
            Parameter('depth_wait_s', value=0.5),
        ])
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.executor.add_node(self.perception)
        self.rgb_pub = self.node.create_publisher(
            Image, '/camera/image_raw', qos_profile_sensor_data)
        self.depth_pub = self.node.create_publisher(
            Image, '/camera/depth/image_raw', qos_profile_sensor_data)
        self.got = {'2d': [], '3d': [], 'status': []}
        self.node.create_subscription(
            Detection2DArray, '/perception/detections_2d', self.got['2d'].append, 10)
        self.node.create_subscription(
            Detection3DArray, '/perception/objects_3d', self.got['3d'].append, 10)
        self.node.create_subscription(
            DiagnosticArray, '/perception/status', self.got['status'].append, 10)
        self.spin_until(lambda: self.rgb_pub.get_subscription_count() > 0
                        and self.depth_pub.get_subscription_count() > 0
                        and self.perception.status_pub.get_subscription_count() > 0)

    def spin_until(self, condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.05)
        assert condition(), 'не дождались сообщений'

    def images(self, depth_mode='ok', rgb_frame=FRAME, depth_frame=FRAME, stamp_shift_ns=0):
        width, height, pixels = detector.load_ppm(FIXTURE / 'images' / f'{SAMPLE}.ppm')
        _, _, depth = detector.load_pgm(FIXTURE / 'depth' / 'constant-1m.pgm')
        if depth_mode == 'zero':
            depth = [0] * len(depth)
        rgb = Image(width=width, height=height, encoding='rgb8', step=width * 3,
                    data=detector.encode_rgb8(pixels))
        rgb.header.stamp.sec, rgb.header.stamp.nanosec = 42, 500
        rgb.header.frame_id = rgb_frame
        depth_msg = Image(width=width, height=height, encoding='16UC1', step=width * 2,
                          data=detector.encode_depth16(depth))
        depth_msg.header.stamp.sec, depth_msg.header.stamp.nanosec = 42, 500 + stamp_shift_ns
        depth_msg.header.frame_id = depth_frame
        return rgb, depth_msg

    def send(self, rgb, depth=None):
        if depth is not None:
            self.depth_pub.publish(depth)
            self.spin_until(lambda: len(self.perception.depth_buffer) > 0)
        self.rgb_pub.publish(rgb)
        self.spin_until(lambda: self.got['status'] and self.got['2d'] and self.got['3d'])
        status = self.got['status'][-1].status[0]
        return self.got['2d'][-1], self.got['3d'][-1], status

    def close(self):
        self.executor.shutdown()
        self.perception.destroy_node()
        self.node.destroy_node()


@pytest.fixture
def harness():
    h = Harness()
    yield h
    h.close()


def values(status):
    return {item.key: item.value for item in status.values}


def test_valid_pair_gives_point_by_formula(harness):
    rgb, depth = harness.images()
    det2d, det3d, status = harness.send(rgb, depth)
    assert len(det2d.detections) == 1
    assert det2d.detections[0].results[0].hypothesis.class_id == 'cone'
    assert len(det3d.detections) == 1
    point = det3d.detections[0].bbox.center.position
    assert (point.x, point.y, point.z) == pytest.approx(((5 - 3.5) / 8, (2 - 2.5) / 8, 1.0))
    assert det3d.detections[0].results[0].pose.pose.position.z == pytest.approx(1.0)
    size = det3d.detections[0].bbox.size
    assert (size.x, size.y, size.z) == (0.0, 0.0, 0.0)
    assert status.level == DiagnosticStatus.OK
    assert values(status)['size_estimated'] == 'false'


def test_stamp_and_frame_are_copied_from_rgb(harness):
    rgb, depth = harness.images()
    det2d, det3d, _ = harness.send(rgb, depth)
    for message in (det2d, det3d, harness.got['status'][-1]):
        assert (message.header.stamp.sec, message.header.stamp.nanosec) == (42, 500)
        assert message.header.frame_id == FRAME


def check_unknown(harness, det2d, det3d, status, reason):
    assert len(det2d.detections) == 1, '2D-детекция должна остаться'
    assert len(det3d.detections) == 0, 'координата не должна выдумываться'
    assert status.level == DiagnosticStatus.WARN
    assert values(status)['reason'] == reason


def test_zero_depth_is_unknown(harness):
    rgb, depth = harness.images(depth_mode='zero')
    check_unknown(harness, *harness.send(rgb, depth), detector.ZERO_DEPTH)


def test_missing_depth_is_unknown_after_bounded_wait(harness):
    rgb, _ = harness.images()
    start = time.monotonic()
    check_unknown(harness, *harness.send(rgb), detector.MISSING_DEPTH)
    assert time.monotonic() - start < 3.0


def test_different_stamp_is_unknown(harness):
    rgb, depth = harness.images(stamp_shift_ns=1_000_000)
    check_unknown(harness, *harness.send(rgb, depth), detector.STAMP_MISMATCH)


def test_wrong_frame_is_unknown(harness):
    rgb, depth = harness.images(rgb_frame='camera_link', depth_frame='camera_link')
    det2d, det3d, status = harness.send(rgb, depth)
    check_unknown(harness, det2d, det3d, status, detector.FRAME_MISMATCH)
    assert det2d.header.frame_id == 'camera_link'


def test_invalid_depth_encoding_is_unknown(harness):
    rgb, depth = harness.images()
    depth.encoding = '32FC1'
    check_unknown(harness, *harness.send(rgb, depth), detector.INVALID_DEPTH)
