#!/usr/bin/env python3
"""Audit the actual messages in a PR07 bag before using it for localization."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


def file_sha256(path):
    """Hash the immutable recording without leaving an open file descriptor."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_recording(path):
    """Read clock bounds, frame ownership, sensor stamps and odometry motion."""
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(path), storage_id='mcap'),
                rosbag2_py.ConverterOptions('', ''))
    topics = {t.name: t.type for t in reader.get_all_topics_and_types()}
    required = {'/clock', '/tf', '/tf_static', '/vehicle/scan', '/vehicle/odom'}
    types = {t: get_message(topics[t]) for t in required if t in topics}
    counts = Counter()
    frames = Counter()
    stamps = {}
    first_clock = last_clock = first_pose = last_pose = None
    clock_backwards = False
    distance = 0.0
    path_points = []
    while reader.has_next():
        topic, data, _ = reader.read_next()
        counts[topic] += 1
        if topic not in types:
            continue
        msg = deserialize_message(data, types[topic])
        if topic == '/clock':
            now = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
            clock_backwards |= last_clock is not None and now < last_clock
            if first_clock is None:
                first_clock = now
            last_clock = now
        elif topic in ('/tf', '/tf_static'):
            for tf in msg.transforms:
                frames[(topic, tf.header.frame_id, tf.child_frame_id)] += 1
        else:
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
            record = stamps.setdefault(topic, {'first_s': stamp})
            record.update(last_s=stamp, frame_id=msg.header.frame_id)
            if topic == '/vehicle/odom':
                record['child_frame_id'] = msg.child_frame_id
                p, q = msg.pose.pose.position, msg.pose.pose.orientation
                point = [p.x, p.y, math.atan2(2 * q.w * q.z, 1 - 2 * q.z * q.z)]
                if first_pose is None:
                    first_pose = point
                if last_pose is not None:
                    distance += math.hypot(point[0] - last_pose[0], point[1] - last_pose[1])
                last_pose = point
                if not path_points or stamp - path_points[-1][0] >= 0.5:
                    path_points.append([stamp, *point])
    return {
        'path': str(path), 'topic_types': topics, 'counts': dict(counts),
        'missing_topics': sorted(required - counts.keys()),
        'clock_first_s': None if first_clock is None else first_clock / 1e9,
        'clock_last_s': None if last_clock is None else last_clock / 1e9,
        'duration_s': 0.0 if first_clock is None else (last_clock - first_clock) / 1e9,
        'clock_backwards': clock_backwards, 'sensor_stamps': stamps,
        'transforms': [{'topic': t, 'parent': p, 'child': c, 'count': n}
                       for (t, p, c), n in sorted(frames.items())],
        'odometry_first_pose': first_pose, 'odometry_last_pose': last_pose,
        'distance_m': distance, 'odometry_path': path_points,
        'files_sha256': {f.name: file_sha256(f)
                         for f in sorted(Path(path).glob('*.mcap'))},
    }


def main():
    """Print an audit and optionally save it for evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = inspect_recording(args.bag)
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding='utf-8')
    print(serialized)
    return int(bool(result['missing_topics']) or result['clock_backwards']
               or result['duration_s'] < 30 or result['distance_m'] < 0.5)


if __name__ == '__main__':
    raise SystemExit(main())
