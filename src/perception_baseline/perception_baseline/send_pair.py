"""Отправить одну пару RGB/depth из fixture ПР09 для показа ноды."""

from pathlib import Path
import time

from perception_baseline import detector
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


def make_image(width, height, encoding, step, data):
    return Image(width=width, height=height, encoding=encoding,
                 is_bigendian=False, step=step, data=data)


def main():
    rclpy.init()
    node = Node('send_pair')
    fixture = Path(node.declare_parameter('fixture', '.course-kit/v1/fixtures/pr09').value)
    sample = node.declare_parameter('sample', 'sample-04').value
    # ok — пара как в fixture; zero — нулевая глубина; none — без depth; stamp — другой stamp
    depth_mode = node.declare_parameter('depth_mode', 'ok').value
    frame_id = node.declare_parameter('frame_id', 'camera_optical_frame').value

    rgb_pub = node.create_publisher(Image, '/camera/image_raw', qos_profile_sensor_data)
    depth_pub = node.create_publisher(Image, '/camera/depth/image_raw', qos_profile_sensor_data)
    deadline = time.monotonic() + 5.0
    while rgb_pub.get_subscription_count() == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

    width, height, pixels = detector.load_ppm(fixture / 'images' / f'{sample}.ppm')
    _, _, depth = detector.load_pgm(fixture / 'depth' / 'constant-1m.pgm')
    if depth_mode == 'zero':
        depth = [0] * len(depth)

    stamp = node.get_clock().now().to_msg()
    rgb = make_image(width, height, 'rgb8', width * 3, detector.encode_rgb8(pixels))
    rgb.header.stamp, rgb.header.frame_id = stamp, frame_id
    depth_msg = make_image(width, height, '16UC1', width * 2, detector.encode_depth16(depth))
    depth_msg.header.stamp.sec = stamp.sec
    depth_msg.header.stamp.nanosec = stamp.nanosec
    depth_msg.header.frame_id = frame_id
    if depth_mode == 'stamp':
        depth_msg.header.stamp.nanosec = (stamp.nanosec + 1) % 1_000_000_000

    # depth уходит раньше RGB, чтобы пара не зависела от порядка доставки
    if depth_mode != 'none':
        depth_pub.publish(depth_msg)
        rclpy.spin_once(node, timeout_sec=0.1)
    rgb_pub.publish(rgb)
    node.get_logger().info(
        f'{sample}: depth_mode={depth_mode}, stamp={stamp.sec}.{stamp.nanosec:09d}, '
        f'frame_id={frame_id}')
    rclpy.spin_once(node, timeout_sec=0.5)
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == '__main__':
    main()
