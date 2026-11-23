"""ROS-обёртка детектора: 2D-детекции, точка по глубине и диагностика."""

from collections import deque
import os
import time

from ament_index_python.packages import get_package_share_directory
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from perception_baseline import detector
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from vision_msgs.msg import (
    Detection2D, Detection2DArray, Detection3D, Detection3DArray, ObjectHypothesisWithPose)

LABEL = 'cone'


def _config_path(name):
    return os.path.join(get_package_share_directory('perception_baseline'), 'config', name)


class PerceptionNode(Node):

    def __init__(self, **kwargs):
        super().__init__('perception_baseline', **kwargs)
        detector_path = self.declare_parameter('detector_config', '').value
        calibration_path = self.declare_parameter('calibration', '').value
        self.depth_wait_s = self.declare_parameter('depth_wait_s', 0.5).value
        self.config = detector.load_json(detector_path or _config_path('baseline-detector.json'))
        self.calibration = detector.load_json(calibration_path or _config_path('calibration.json'))
        self.frame_id = self.calibration['frame_id']

        self.depth_buffer = deque(maxlen=10)
        self.pending = []
        self.rgb_sub = self.create_subscription(
            Image, '/camera/image_raw', self.on_rgb, qos_profile_sensor_data)
        self.depth_sub = self.create_subscription(
            Image, '/camera/depth/image_raw', self.on_depth, qos_profile_sensor_data)
        self.det2d_pub = self.create_publisher(Detection2DArray, '/perception/detections_2d', 10)
        self.det3d_pub = self.create_publisher(Detection3DArray, '/perception/objects_3d', 10)
        self.status_pub = self.create_publisher(DiagnosticArray, '/perception/status', 10)
        # ожидание depth ограничено: без пары через depth_wait_s выдаём unknown
        self.timer = self.create_timer(0.05, self.flush_pending)

    def on_rgb(self, msg):
        self.pending.append((msg, time.monotonic()))
        self.flush_pending()

    def on_depth(self, msg):
        self.depth_buffer.append(msg)
        self.flush_pending()

    def find_depth(self, stamp):
        for depth in reversed(self.depth_buffer):
            if (depth.header.stamp.sec, depth.header.stamp.nanosec) == (stamp.sec, stamp.nanosec):
                return depth
        return None

    def flush_pending(self):
        waiting = []
        for rgb, received in self.pending:
            depth = self.find_depth(rgb.header.stamp)
            if depth is not None:
                self.process(rgb, depth, None)
            elif time.monotonic() - received >= self.depth_wait_s:
                reason = detector.STAMP_MISMATCH if self.depth_buffer else detector.MISSING_DEPTH
                self.process(rgb, None, reason)
            else:
                waiting.append((rgb, received))
        self.pending = waiting

    def check_depth(self, rgb, depth):
        """Вернуть (причина, значения глубины); причина None, если глубина пригодна."""
        if rgb.header.frame_id != self.frame_id or depth.header.frame_id != rgb.header.frame_id:
            return detector.FRAME_MISMATCH, None
        if (depth.width, depth.height) != (rgb.width, rgb.height):
            return detector.INVALID_DEPTH, None
        try:
            values = detector.decode_depth16(
                depth.width, depth.height, depth.encoding, depth.step,
                depth.is_bigendian, depth.data)
        except ValueError:
            return detector.INVALID_DEPTH, None
        return None, values

    def process(self, rgb, depth, reason):
        header = rgb.header
        try:
            pixels = detector.decode_rgb8(rgb.width, rgb.height, rgb.encoding, rgb.step, rgb.data)
        except ValueError as error:
            self.publish(header, [], [], DiagnosticStatus.ERROR, 'invalid_image', str(error))
            return
        boxes = detector.detect_pixels(rgb.width, rgb.height, pixels, self.config)

        values = None
        if reason is None:
            reason, values = self.check_depth(rgb, depth)

        detections_2d = []
        objects_3d = []
        point_reasons = []
        for index, box in enumerate(boxes):
            detections_2d.append(self.make_2d(header, index, box))
            if values is None:
                continue
            u, v = detector.depth_pixel(box)
            raw = values[v * rgb.width + u]
            if raw == 0:
                point_reasons.append(detector.ZERO_DEPTH)
                continue
            objects_3d.append(self.make_3d(header, index, detector.project(
                u, v, raw, self.calibration)))

        if not boxes:
            level, reason = DiagnosticStatus.OK, 'no_detections'
        elif reason is None and len(objects_3d) == len(boxes):
            level, reason = DiagnosticStatus.OK, 'ok'
        else:
            level, reason = DiagnosticStatus.WARN, reason or point_reasons[0]
        self.publish(header, detections_2d, objects_3d, level, reason, '')

    def make_2d(self, header, index, box):
        x, y, width, height = box
        detection = Detection2D()
        detection.header = header
        detection.id = f'det-{index}'
        detection.bbox.center.position.x = x + width / 2.0
        detection.bbox.center.position.y = y + height / 2.0
        detection.bbox.size_x = float(width)
        detection.bbox.size_y = float(height)
        detection.results.append(self.hypothesis())
        return detection

    def make_3d(self, header, index, point):
        detection = Detection3D()
        detection.header = header
        detection.id = f'det-{index}'
        detection.bbox.center.position.x, detection.bbox.center.position.y, \
            detection.bbox.center.position.z = point
        # размер и ориентация не оценивались, bbox.size остаётся нулевым
        hypothesis = self.hypothesis()
        hypothesis.pose.pose.position = detection.bbox.center.position
        detection.results.append(hypothesis)
        return detection

    def hypothesis(self):
        result = ObjectHypothesisWithPose()
        result.hypothesis.class_id = LABEL
        # у baseline нет оценки уверенности, 1.0 только означает «найдено»
        result.hypothesis.score = 1.0
        return result

    def publish(self, header, detections_2d, objects_3d, level, reason, detail):
        self.det2d_pub.publish(Detection2DArray(header=header, detections=detections_2d))
        self.det3d_pub.publish(Detection3DArray(header=header, detections=objects_3d))
        status = DiagnosticStatus(
            level=level, name='perception_baseline/spatial', message=reason,
            hardware_id=header.frame_id)
        status.values = [
            KeyValue(key='reason', value=reason),
            KeyValue(key='stamp', value=f'{header.stamp.sec}.{header.stamp.nanosec:09d}'),
            KeyValue(key='frame_id', value=header.frame_id),
            KeyValue(key='detections_2d', value=str(len(detections_2d))),
            KeyValue(key='objects_3d', value=str(len(objects_3d))),
            KeyValue(key='point', value='surface point on ray through bbox pixel (u, v)'),
            KeyValue(key='size_estimated', value='false'),
            KeyValue(key='orientation_estimated', value='false'),
        ]
        if detail:
            status.values.append(KeyValue(key='detail', value=detail))
        self.status_pub.publish(DiagnosticArray(header=header, status=[status]))


def main():
    rclpy.init()
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
