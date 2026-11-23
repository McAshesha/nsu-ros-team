import os
import time

from paths import FIXTURES, PROMPT, SCHEMA
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from robotics_course_interfaces.msg import SceneDescription
from rosgraph_msgs.msg import Clock
from scene_adapter import contract
from scene_adapter.node import SceneAdapterNode


@pytest.fixture(scope='module', autouse=True)
def ros():
    os.environ['ROS_DOMAIN_ID'] = '72'
    rclpy.init()
    yield
    rclpy.try_shutdown()


def run_mock(fixture, now_s):
    node = SceneAdapterNode(parameter_overrides=[
        Parameter('use_sim_time', value=True),
        Parameter('mode', value='mock'),
        Parameter('schema_path', value=str(SCHEMA)),
        Parameter('fixture_path', value=str(FIXTURES / fixture)),
        Parameter('prompt_path', value=str(PROMPT)),
    ])
    probe = rclpy.create_node('scene_probe')
    clock_pub = probe.create_publisher(Clock, '/clock', 10)
    received = []
    probe.create_subscription(SceneDescription, '/perception/scene', received.append, 10)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(probe)
    clock = Clock()
    clock.clock.sec, clock.clock.nanosec = int(now_s), round((now_s % 1) * 1e9)
    deadline = time.monotonic() + 10.0
    # ждём сцену, посчитанную уже после получения нашего /clock
    while time.monotonic() < deadline and not (received and node.now_s() == pytest.approx(now_s)):
        clock_pub.publish(clock)
        executor.spin_once(timeout_sec=0.05)
    received.clear()
    while time.monotonic() < deadline and not received:
        executor.spin_once(timeout_sec=0.05)
    executor.shutdown()
    node.destroy_node()
    probe.destroy_node()
    assert received, 'на /perception/scene ничего не пришло'
    return received[-1]


def test_mock_clear_is_published_valid():
    msg = run_mock('scene-clear.json', 0.1)
    assert msg.status == SceneDescription.STATUS_VALID
    assert msg.traffic_light == SceneDescription.LIGHT_GREEN
    assert msg.has_stop_line and msg.stop_line_distance_m == pytest.approx(2.4, abs=1e-6)
    assert not msg.has_obstacle
    assert msg.source == 'mock'


def test_mock_stale_is_published_unknown():
    msg = run_mock('scene-stale.json', 2.0)
    assert msg.status == SceneDescription.STATUS_UNKNOWN
    assert msg.status_reason == contract.STALE_INPUT
    assert (msg.header.stamp.sec, msg.header.frame_id) == (1, 'base_link')
