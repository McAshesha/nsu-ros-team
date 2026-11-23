#!/usr/bin/env python3
"""Measure AMCL on the first /clock epoch without inventing missed TF queries."""

import hashlib
import json
import math
from pathlib import Path
import statistics

from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformException, TransformListener


NS = 1_000_000_000


def stamp_ns(stamp):
    """Keep interval boundaries exact in integer nanoseconds."""
    return stamp.sec * NS + stamp.nanosec


class MeasurementWindow:
    """Bookkeep one actual query per 0.1 s bucket in [t0+10, t0+30)."""

    def __init__(self):
        self.first = None
        self.last = None
        self.next_bucket = 0
        self.queries = []
        self.poses = []
        self.errors = []

    def clock(self, now, lookup):
        """Call lookup at most once; skipped buckets invalidate the experiment."""
        if self.first is None:
            self.first = now
        if self.last is not None and now < self.last:
            self.errors.append('Recorded clock moved backwards; restart all processes')
        self.last = now
        if self.errors:
            return
        elapsed = now - self.first
        if elapsed < 10 * NS or elapsed >= 30 * NS:
            return
        bucket = (elapsed - 10 * NS) // (NS // 10)
        if bucket < self.next_bucket:
            return
        if bucket != self.next_bucket:
            self.errors.append(f'Missed query bucket {self.next_bucket}; observed {bucket}')
            return
        success, detail = lookup()
        self.queries.append({'bucket': bucket, 'clock_s': now / NS,
                             'success': success, **detail})
        self.next_bucket = bucket + 1

    def pose(self, stamp, covariance):
        """Store stamped samples; decide membership by header.stamp at finalization."""
        value = float(covariance[0] + covariance[7])
        if math.isfinite(value) and value >= 0:
            self.poses.append((stamp, value))
        else:
            self.errors.append('Invalid AMCL covariance')

    def finish(self):
        """Reject incomplete runs and compute only measured values."""
        errors = list(self.errors)
        if self.first is None or self.last - self.first < 30 * NS:
            errors.append('Recording ended before the complete warmup and evaluation window')
        if len(self.queries) != 200:
            errors.append(f'Expected 200 actual queries, got {len(self.queries)}')
        if errors:
            raise ValueError('; '.join(errors))
        values = [value for stamp, value in self.poses
                  if self.first + 10 * NS <= stamp < self.first + 30 * NS]
        successful = sum(q['success'] for q in self.queries)
        if len(values) < 10:
            raise ValueError(f'Expected at least 10 AMCL poses in the window, got {len(values)}')
        return {
            'warmup_s': 10.0, 'duration_s': 20.0,
            'tf_queries_total': len(self.queries), 'tf_queries_successful': successful,
            'tf_availability': successful / len(self.queries),
            'amcl_pose_samples': len(values),
            'median_xy_covariance_m2': statistics.median(values),
        }


class LocalizationMeasurement(Node):
    """Observe replay and AMCL; never publish TF or a second clock."""

    def __init__(self):
        super().__init__('localization_measurement', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)])
        self.declare_parameter('output', 'evidence/pr08/localization.json')
        self.declare_parameter('recording', 'fixtures/pr07-sensors')
        self.declare_parameter('map_yaml', 'evidence/pr08/map.yaml')
        self.declare_parameter('map_pgm', 'evidence/pr08/map.pgm')
        self.window = MeasurementWindow()
        self.buffer = Buffer(node=self)
        self.listener = TransformListener(self.buffer, self)
        self.sensor_stats = {}
        self.overlays = []
        self.pose_trace = []
        self.warmup_queries = []
        self.create_subscription(Clock, '/clock', self.on_clock,
                                 QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.on_pose, 100)
        self.create_subscription(LaserScan, '/vehicle/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/vehicle/odom', self.on_odom, qos_profile_sensor_data)
        self.get_logger().info('READY: waiting for the first recorded /clock')

    def lookup(self):
        try:
            transform = self.buffer.lookup_transform('map', 'odom', Time())
            return True, {'transform_stamp_s': stamp_ns(transform.header.stamp) / NS}
        except TransformException as error:
            return False, {'error': str(error)}

    def on_clock(self, msg):
        first = self.window.first is None
        self.window.clock(stamp_ns(msg.clock), self.lookup)
        if first:
            self.get_logger().info(f't0={self.window.first / NS:.9f}')
        elapsed = stamp_ns(msg.clock) - self.window.first
        if 0 <= elapsed < 10 * NS and elapsed >= len(self.warmup_queries) * NS:
            success, detail = self.lookup()
            self.warmup_queries.append({'clock_s': stamp_ns(msg.clock) / NS,
                                        'success': success, **detail})
        if len(self.window.queries) == 200 and self.window.next_bucket == 200:
            self.get_logger().info('Collected 200 actual queries; waiting for replay to end')
            self.window.next_bucket = 201

    def on_pose(self, msg):
        stamp = stamp_ns(msg.header.stamp)
        self.window.pose(stamp, msg.pose.covariance)
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        self.pose_trace.append({'stamp_s': stamp / NS, 'x': p.x, 'y': p.y,
                                'yaw': math.atan2(2 * q.w * q.z, 1 - 2 * q.z * q.z),
                                'xy_covariance_m2': msg.pose.covariance[0] + msg.pose.covariance[7]})

    def sensor_stamp(self, topic, stamp):
        now = self.window.last
        if now is None:
            return
        seconds = stamp_ns(stamp) / NS
        lag = now / NS - seconds
        stats = self.sensor_stats.setdefault(topic, {
            'first_stamp_s': seconds, 'min_clock_minus_stamp_s': lag,
            'max_clock_minus_stamp_s': lag, 'count': 0})
        stats.update(last_stamp_s=seconds, clock_at_arrival_s=now / NS,
                     min_clock_minus_stamp_s=min(stats['min_clock_minus_stamp_s'], lag),
                     max_clock_minus_stamp_s=max(stats['max_clock_minus_stamp_s'], lag),
                     count=stats['count'] + 1)

    def on_odom(self, msg):
        self.sensor_stamp('/vehicle/odom', msg.header.stamp)

    def on_scan(self, msg):
        self.sensor_stamp('/vehicle/scan', msg.header.stamp)
        stamp = stamp_ns(msg.header.stamp) / NS
        if self.window.first is None or stamp < self.window.first / NS + 10:
            return
        if self.overlays and stamp - self.overlays[-1]['stamp_s'] < 5:
            return
        try:
            tf = self.buffer.lookup_transform('map', msg.header.frame_id,
                                              Time.from_msg(msg.header.stamp))
        except TransformException:
            return
        t, q = tf.transform.translation, tf.transform.rotation
        yaw = math.atan2(2 * q.w * q.z, 1 - 2 * q.z * q.z)
        points = [[t.x + r * math.cos(yaw + msg.angle_min + i * msg.angle_increment),
                   t.y + r * math.sin(yaw + msg.angle_min + i * msg.angle_increment)]
                  for i, r in enumerate(msg.ranges)
                  if math.isfinite(r) and msg.range_min <= r <= msg.range_max]
        self.overlays.append({'stamp_s': stamp, 'lidar_xy': [t.x, t.y], 'points': points})

    def save(self):
        """Save raw observations even if the experiment cannot produce a valid result."""
        output = Path(self.get_parameter('output').value)
        output.parent.mkdir(parents=True, exist_ok=True)
        debug = {
            'first_clock_s': None if self.window.first is None else self.window.first / NS,
            'last_clock_s': None if self.window.last is None else self.window.last / NS,
            'queries': self.window.queries, 'poses': self.pose_trace,
            'warmup_queries': self.warmup_queries,
            'sensor_stamps': self.sensor_stats, 'scan_overlays': self.overlays,
            'errors': list(self.window.errors),
        }
        try:
            evaluation = self.window.finish()
        except ValueError as error:
            debug['errors'].append(str(error))
            output.with_suffix('.observations.json').write_text(
                json.dumps(debug, indent=2, ensure_ascii=False), encoding='utf-8')
            if output.exists():
                output.replace(output.with_suffix('.previous.json'))
            raise
        debug['evaluation_start_s'] = self.window.first / NS + 10
        debug['evaluation_end_s'] = self.window.first / NS + 30
        output.with_suffix('.observations.json').write_text(
            json.dumps(debug, indent=2, ensure_ascii=False), encoding='utf-8')
        result = {
            'schema_version': 1,
            'map_sha256': {
                key: hashlib.sha256(Path(self.get_parameter(param).value).read_bytes()).hexdigest()
                for key, param in [('map.yaml', 'map_yaml'), ('map.pgm', 'map_pgm')]},
            'recording': {'path': self.get_parameter('recording').value,
                          'duration_s': (self.window.last - self.window.first) / NS},
            'initial_pose': {'x_m': 0.0, 'y_m': 0.0, 'yaw_rad': 0.0},
            'evaluation': evaluation,
            'defect': {
                'before_base_frame_id': 'chassis', 'after_base_frame_id': 'base_link',
                'observed_symptom': 'chassis is absent in recorded TF; AMCL cannot obtain '
                                    'the laser-to-base transform or publish map -> odom. '
                                    'See defect-launch.txt and tf.md.'},
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(json.dumps(evaluation, indent=2), flush=True)


def main():
    """Run until replay finishes and the operator sends Ctrl+C."""
    rclpy.init()
    node = LocalizationMeasurement()
    exit_code = 0
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        try:
            node.save()
        except ValueError as error:
            print(f'INVALID EXPERIMENT: {error}', flush=True)
            exit_code = 1
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
