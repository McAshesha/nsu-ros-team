#!/usr/bin/env python3
"""Run fresh baseline, faulty-frame and corrected AMCL processes on one fixed bag."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


EVIDENCE = Path('evidence/pr08')


def start(command, name):
    path = EVIDENCE / f'{name}.txt'
    log = path.open('w')
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    log.close()
    return process, path


def stop(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)


def wait_log(process, path, phrase, timeout=50):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if phrase in path.read_text(errors='replace'):
            return
        if process.poll() is not None:
            raise RuntimeError(f'{path}: process exited with {process.returncode}')
        time.sleep(0.1)
    raise TimeoutError(f'{path}: did not reach {phrase!r}')


def capture(command, name, timeout=30):
    process = subprocess.Popen(['stdbuf', '-oL', '-eL', *command], text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        text = output + f'\nexit={process.returncode}\n'
    except subprocess.TimeoutExpired:
        stop(process)
        output, _ = process.communicate()
        text = output + '\nexit=124 (timeout)\n'
    (EVIDENCE / f'{name}.txt').write_text('$ ' + ' '.join(command) + '\n' + text)
    return text


def experiment(kind, rate):
    launch = meter = player = None
    print(f'Starting {kind} with fresh processes, ROS_DOMAIN_ID={os.environ["ROS_DOMAIN_ID"]}', flush=True)
    params = 'amcl-defect.yaml' if kind == 'defect' else 'amcl.yaml'
    try:
        launch, launch_log = start([
            'ros2', 'launch', 'localization_case', 'localization.launch.py',
            f'params_file:={Path("src/localization_case/config", params).resolve()}',
            f'map:={Path("evidence/pr08/map.yaml").resolve()}'], f'{kind}-launch')
        wait_log(launch, launch_log, 'Managed nodes are active')
        for node in ('map_server', 'amcl'):
            for attempt in range(3):
                state = capture(['ros2', 'lifecycle', 'get', f'/{node}',
                                 '--no-daemon', '--spin-time', '3'],
                                f'{kind}-{node}-state')
                if 'active [3]' in state:
                    break
                time.sleep(1)
            if 'active [3]' not in state:
                raise RuntimeError(f'{node} was not active: {state}')
        meter, meter_log = start([
            'ros2', 'run', 'localization_case', 'measure_localization.py', '--ros-args',
            '-p', f'output:=evidence/pr08/{"localization" if kind == "fixed" else kind}.json'],
            f'{kind}-measurement')
        wait_log(meter, meter_log, 'READY:')
        # Discovery must finish before the first /clock in the immutable bag.
        time.sleep(2)
        player, _ = start(['ros2', 'bag', 'play', 'fixtures/pr07-sensors',
                           '--rate', str(rate)], f'{kind}-player')
        wait_log(meter, meter_log, 't0=')
        if kind in ('baseline', 'defect'):
            time.sleep(7 / rate)
            capture(['ros2', 'run', 'tf2_ros', 'tf2_echo', 'map', 'odom',
                     '--ros-args', '-p', 'use_sim_time:=true'], f'{kind}-tf-echo', timeout=9)
            if kind == 'baseline':
                capture(['ros2', 'topic', 'echo', '/amcl_pose', '--once'], 'baseline-amcl-pose')
            # The clock must remain alive while faulty AMCL shuts down in Jazzy.
            stop(launch)
            launch = None
            stop(player)
            player = None
            stop(meter)
            meter = None
        else:
            capture(['ros2', 'topic', 'info', '/tf', '-v', '--no-daemon', '--spin-time', '3'],
                    'fixed-tf-publishers')
            capture(['ros2', 'topic', 'info', '/tf_static', '-v', '--no-daemon', '--spin-time', '3'],
                    'fixed-tf-static-publishers')
            capture(['ros2', 'run', 'tf2_ros', 'tf2_echo', 'map', 'odom',
                     '--ros-args', '-p', 'use_sim_time:=true'], 'fixed-tf-echo', timeout=9)
            capture(['ros2', 'run', 'tf2_tools', 'view_frames', '-o', 'evidence/pr08/frames', '--ros-args',
                     '-p', 'use_sim_time:=true'], 'fixed-view-frames', timeout=25)
            player.wait(timeout=180 / rate)
            if player.returncode:
                raise RuntimeError(f'Player failed with {player.returncode}')
            time.sleep(1)
            stop(meter)
            if meter.returncode != 0:
                raise RuntimeError(f'Measurement failed: {meter_log.read_text()}')
            meter = None
            result = json.loads((EVIDENCE / 'localization.json').read_text())
            print(json.dumps(result['evaluation'], indent=2), flush=True)
    finally:
        stop(launch)
        stop(player)
        stop(meter)
    print(f'Finished {kind}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['baseline', 'defect', 'fixed'])
    parser.add_argument('--rate', type=float, default=0.5)
    args = parser.parse_args()
    if args.rate <= 0:
        parser.error('--rate must be positive')
    os.environ['ROS_DOMAIN_ID'] = os.environ.get('ROS_DOMAIN_ID', '169')
    os.environ['PYTHONUNBUFFERED'] = '1'
    for kind in ([args.only] if args.only else ['baseline', 'defect', 'fixed']):
        experiment(kind, args.rate)


if __name__ == '__main__':
    main()
