#!/usr/bin/env python3
"""Record 35 simulated seconds of straight motion in the running PR07 simulation."""

import os
from pathlib import Path
import signal
import subprocess
import time

from ackermann_msgs.msg import AckermannDriveStamped
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock


def main():
    rclpy.init()
    node = Node('pr08_recording_driver', parameter_overrides=[
        rclpy.parameter.Parameter('use_sim_time', value=True)])
    publisher = node.create_publisher(AckermannDriveStamped, '/drive/safe', 10)
    current = [None]
    subscription = node.create_subscription(
        Clock, '/clock', lambda m: current.__setitem__(0, m.clock.sec + m.clock.nanosec / 1e9),
        QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
    deadline = time.monotonic() + 30
    while current[0] is None:
        rclpy.spin_once(node, timeout_sec=0.1)
        if time.monotonic() > deadline:
            raise RuntimeError('Simulation clock is absent')
    root = Path('fixtures/pr07-sensors')
    if root.exists():
        backup = root.with_name('pr07-sensors-before-pr08')
        if backup.exists():
            raise FileExistsError(f'Preserve {backup} before recording again')
        root.rename(backup)
    log = Path('evidence/pr08/recording.txt').open('w')
    command = ['ros2', 'bag', 'record', '--storage', 'mcap', '--use-sim-time',
               '-o', str(root), '--topics', '/vehicle/scan', '/vehicle/odom',
               '/vehicle/imu', '/tf', '/tf_static', '/clock']
    print(' '.join(command), flush=True)
    recorder = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline = time.monotonic() + 40
        while 'All requested topics are subscribed' not in Path('evidence/pr08/recording.txt').read_text():
            rclpy.spin_once(node, timeout_sec=0.05)
            if time.monotonic() > deadline or recorder.poll() is not None:
                raise RuntimeError('Recorder did not subscribe to all required topics')
        start = current[0]
        next_command = start
        while current[0] - start < 37.0:
            rclpy.spin_once(node, timeout_sec=0.02)
            if current[0] < next_command:
                continue
            next_command = current[0] + 0.05
            msg = AckermannDriveStamped()
            msg.header.stamp = node.get_clock().now().to_msg()
            msg.drive.speed = 0.18 if current[0] - start > 2.0 else 0.0
            publisher.publish(msg)
            if recorder.poll() is not None:
                raise RuntimeError('Recorder stopped unexpectedly')
        print(f'Recorded driving interval: {start:.3f} .. {current[0]:.3f}', flush=True)
    finally:
        for _ in range(10):
            msg = AckermannDriveStamped()
            msg.header.stamp = node.get_clock().now().to_msg()
            publisher.publish(msg)
            rclpy.spin_once(node, timeout_sec=0.05)
        os.killpg(recorder.pid, signal.SIGINT)
        recorder.wait(timeout=20)
        log.close()
        node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
