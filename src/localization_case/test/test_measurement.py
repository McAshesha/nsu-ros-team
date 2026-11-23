"""Verify time boundaries, missed samples and truthful measurement accounting."""

import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'measure_localization', Path(__file__).parents[1] / 'scripts/measure_localization.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NS = module.NS


def run_window(failed=()):
    window = module.MeasurementWindow()
    start = 42 * NS
    for i in range(310):
        window.clock(start + i * (NS // 10), lambda: (i not in failed, {}))
    for i in range(20):
        covariance = [0.0] * 36
        covariance[0], covariance[7] = 0.05, 0.02
        window.pose(start + (10 + i) * NS, covariance)
    return window


def test_nonzero_epoch_and_exact_query_count():
    result = run_window().finish()
    assert result['tf_queries_total'] == 200
    assert result['tf_availability'] == 1.0
    assert result['amcl_pose_samples'] == 20
    assert result['median_xy_covariance_m2'] == pytest.approx(0.07)


def test_tf_failures_count_in_denominator():
    result = run_window(failed=range(100, 110)).finish()
    assert result['tf_queries_successful'] == 190
    assert result['tf_availability'] == 0.95


def test_pose_window_is_half_open_and_uses_header_time():
    window = run_window()
    cov = [10.0] * 36
    window.pose(52 * NS - 1, cov)
    window.pose(72 * NS, cov)
    assert window.finish()['amcl_pose_samples'] == 20


def test_missing_query_is_not_replaced_by_a_burst():
    window = module.MeasurementWindow()
    calls = []
    for now in (42 * NS, 52 * NS, 52 * NS + 200_000_000, 52 * NS + 201_000_000):
        window.clock(now, lambda: (calls.append(now) is None, {}))
    assert len(calls) == 1
    with pytest.raises(ValueError, match='Missed query bucket'):
        window.finish()


def test_backwards_clock_invalidates_run():
    window = run_window()
    window.clock(0, lambda: (True, {}))
    with pytest.raises(ValueError, match='backwards'):
        window.finish()


def test_short_recording_is_rejected():
    window = run_window()
    window.last = window.first + 29 * NS
    with pytest.raises(ValueError, match='ended before'):
        window.finish()


def test_repeated_clock_does_not_duplicate_query():
    window = run_window()
    window.clock(window.last, lambda: pytest.fail('Duplicate lookup'))
    assert len(window.queries) == 200


def test_too_few_poses_is_rejected():
    window = run_window()
    window.poses = window.poses[:9]
    with pytest.raises(ValueError, match='at least 10'):
        window.finish()


def test_nonfinite_covariance_is_rejected():
    window = run_window()
    window.pose(55 * NS, [float('nan')] * 36)
    with pytest.raises(ValueError, match='Invalid AMCL covariance'):
        window.finish()
