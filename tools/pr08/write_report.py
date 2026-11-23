#!/usr/bin/env python3
"""Describe measured evidence honestly; never create or invent a Git commit."""

import json
from pathlib import Path
import subprocess
import sys


def main():
    folder = Path('evidence/pr08')
    result = json.loads((folder / 'localization.json').read_text())
    observed = json.loads((folder / 'localization.observations.json').read_text())
    broken = json.loads((folder / 'defect.observations.json').read_text())
    audit = json.loads((folder / 'recording-audit.json').read_text())
    good_config = Path('src/localization_case/config/amcl.yaml').read_bytes()
    bad_config = Path('src/localization_case/config/amcl-defect.yaml').read_bytes()
    assert good_config == Path('.course-kit/v1/fixtures/pr08/amcl.yaml').read_bytes()
    assert bad_config == good_config.replace(b'base_frame_id: base_link', b'base_frame_id: chassis')
    assert all(not q['success'] for q in broken['warmup_queries'])
    assert len(broken['warmup_queries']) >= 5
    error = next(line for line in (folder / 'defect-launch.txt').read_text().splitlines()
                 if "Couldn't transform from lidar_link to chassis" in line)
    assert '0 errors, 0 failures' in (folder / 'tests.txt').read_text()
    validator = [sys.executable, '.course-kit/v1/tools/validate_localization.py',
                 str(folder / 'localization.json'), '--schema',
                 '.course-kit/v1/fixtures/pr08/localization-result-v1.schema.json',
                 '--map-yaml', str(folder / 'map.yaml'), '--map-pgm', str(folder / 'map.pgm')]
    validation = subprocess.run(validator, text=True, capture_output=True)
    (folder / 'schema-check.txt').write_text(validation.stdout + validation.stderr)
    if validation.returncode:
        raise RuntimeError(validation.stdout + validation.stderr)
    metrics = result['evaluation']
    stamps = observed['sensor_stamps']
    start, end = observed['evaluation_start_s'], observed['evaluation_end_s']
    rows = '\n'.join(
        f"| `{name}` | {s['first_stamp_s']:.3f} | {s['last_stamp_s']:.3f} | "
        f"{s['min_clock_minus_stamp_s']:.3f} … {s['max_clock_minus_stamp_s']:.3f} |"
        for name, s in stamps.items())
    tf_text = f'''# TF: контролируемый отказ и восстановление

Оба опыта выполнены в существующем контейнере `practical_hofstadter`, ROS 2 Jazzy.
Карта, MCAP, начальная гипотеза `(0, 0, 0)` и обязательный профиль фиксированы.
Отличается только `base_frame_id`; процессам и буферам TF не даётся пережить опыт.

## Неизменные входы

- Course kit: `v1-w08`, SHA-256 архива
  `aea8efd0a51668af63f2e475b82bfa28bd76c21f20d8afea6b136d43a56a88fb`.
- `map.yaml`: `{result['map_sha256']['map.yaml']}`.
- `map.pgm`: `{result['map_sha256']['map.pgm']}`.
- MCAP: `{audit['files_sha256']['pr07-sensors_0.mcap']}`.
- Полная запись: `/clock` от {audit['clock_first_s']:.3f} до {audit['clock_last_s']:.3f} с,
  длительность {audit['duration_s']:.3f} с.
- Путь по записанной одометрии: {audit['distance_m']:.3f} м.
- Исходная неподвижная запись сохранена отдельно, см. README.md.

## Владельцы

| Связь | Первоначальный источник | Источник во время replay | Топик |
| --- | --- | --- | --- |
| `map → odom` | AMCL | Только `/amcl` | `/tf` |
| `odom → base_link` | Адаптер одометрии ПР07 | `/rosbag2_player` | `/tf` |
| `base_link → lidar_link` | robot_state_publisher ПР06 | `/rosbag2_player` | `/tf_static` |

В аудите bag нет `map → odom`: replay не конкурирует с AMCL за эту связь.
В `fixed-tf-publishers.txt` видны AMCL и player, а в
`fixed-tf-static-publishers.txt` — один player. Два издателя `/tf` допустимы,
поскольку они публикуют разные рёбра дерева. Новые odom adapter,
robot_state_publisher, Gazebo, bridge и static_transform_publisher во время replay
не запускаются. `view_frames` показывает связное дерево; его значение
`default_authority` само по себе не идентифицирует исходного владельца записи.

## До исправления

```bash
ros2 launch localization_case localization.launch.py \\
  params_file:=$PWD/src/localization_case/config/amcl-defect.yaml \\
  map:=$PWD/evidence/pr08/map.yaml
ros2 run localization_case measure_localization.py --ros-args \\
  -p output:=evidence/pr08/defect.json
ros2 bag play fixtures/pr07-sensors --rate 0.5
ros2 run tf2_ros tf2_echo map odom --ros-args -p use_sim_time:=true
```

Первая сохранённая ошибка AMCL:

```text
{error}
```

Та же команда `tf2_echo` сообщает `Invalid frame ID "map" ... frame does not exist`.
В диагностике разгона выполнено {len(broken['warmup_queries'])} запросов `map → odom`,
успешных {sum(q['success'] for q in broken['warmup_queries'])}.
`defect.observations.json` содержит сами исключения. Это короткий опыт;
он намеренно не выдаётся за полное 20-секундное измерение.
Сначала остановлен launch, пока `/clock` ещё поступал, затем player.

Причина: `chassis` отсутствует в записанном дереве. AMCL не может преобразовать
лидар в выбранную систему корпуса. Исправляется имя параметра, а не карта
и не установка пакетов.

## После исправления

Запущены новые процессы с `params_file:=$PWD/src/localization_case/config/amcl.yaml`.
В остальном команды и входы прежние. Обе lifecycle-ноды имеют `active [3]`.
Та же команда `tf2_echo` теперь выводит Translation/Rotation и матрицы,
см. `fixed-tf-echo.txt`. Код 124 у этой непрерывной команды означает остановку
по лимиту наблюдения, а не отсутствие преобразования; важен её вывод.

- Первый принятый `/clock`: {observed['first_clock_s']:.3f} с.
- Последний принятый `/clock`: {observed['last_clock_s']:.3f} с.
- Окно: [{start:.3f}; {end:.3f}) с, разгон 10 с, оценка 20 с.
- Реальные TF-запросы: {metrics['tf_queries_total']}.
- Успешные: {metrics['tf_queries_successful']}.
- Доступность: {metrics['tf_availability']:.1%}, порог 95%.
- Сообщений `/amcl_pose` в том же окне: {metrics['amcl_pose_samples']}.
- Медиана `covariance[0] + covariance[7]`:
  {metrics['median_xy_covariance_m2']:.9f} м², порог 0,25 м².

Каждый запрос и stamp исходных поз сохранены в `localization.observations.json`.
Пропуски не заменялись повторными запросами к одному состоянию буфера.

## Временная согласованность и предел вывода

| Сообщение | Первый header.stamp, с | Последний header.stamp, с | `/clock` при приёме минус stamp, с |
| --- | --- | --- | --- |
{rows}

Малые транспортные задержки ожидаемы: время измерения датчика предшествует
доставке. Все stamp лежат на шкале записанного `/clock`, а не системных часов.
`map → odom` имеет запас `transform_tolerance=0.2` с; его stamp может быть
немного впереди текущих часов. Последний TF доступен не обязательно
на точное время каждого скана. Отдельно несколько сканов преобразованы
в `map` по их собственному stamp для графика `localization.png`.

В RViz с `Fixed Frame=map` проверены `/map`, `/vehicle/scan` и TF:
контуры сканов следуют стенам коридора, но видны остаточные смещения
и различия у выступов. Это качественная проверка согласованности,
а не независимое измерение ошибки. Ковариация характеризует уверенность AMCL;
малое значение не гарантирует верную абсолютную позу. Ground truth не измерялась.

## Повтор

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=169
python3 tools/pr08/run_experiments.py --rate 0.5
python3 tools/pr08/plot_results.py
python3 tools/pr08/write_report.py
```

Сборка и девять тестов — `build.txt`, `tests.txt`; специализированный
валидатор схемы, метрик и хэшей — `schema-check.txt`.
В `report.json` указан SHA коммита реализации, предшествующего коммиту отчёта.
'''
    (folder / 'tf.md').write_text(tf_text, encoding='utf-8')
    report_path = folder / 'report.json'
    previous = json.loads(report_path.read_text()) if report_path.exists() else {}
    report = {
        'schema_version': 1, 'practice_id': 'PR08', 'commit': previous.get('commit'),
        'course_kit': {'version': 'v1-w08',
                       'archive_sha256': 'aea8efd0a51668af63f2e475b82bfa28bd76c21f20d8afea6b136d43a56a88fb'},
        'commands': [
            'colcon build --symlink-install --packages-select localization_case',
            'colcon test --packages-select localization_case --event-handlers console_direct+',
            'colcon test-result --test-result-base build/localization_case --verbose',
            'python3 src/localization_case/scripts/inspect_recording.py fixtures/pr07-sensors '
            '--output evidence/pr08/recording-audit.json',
            'python3 tools/pr08/run_experiments.py --rate 0.5',
            'python3 tools/pr08/plot_results.py', ' '.join(validator),
            'python3 .course-kit/v1/tools/check_practice.py PR08 --submission .'],
        'tests': [
            {'name': 'colcon build localization_case', 'status': 'passed'},
            {'name': '9 pytest cases for time boundaries and truthful accounting', 'status': 'passed'},
            {'name': 'Live AMCL replay and TF availability/covariance thresholds', 'status': 'passed'},
            {'name': 'validate_localization.py: schema, metrics, map hashes', 'status': 'passed'},
            {'name': 'check_practice.py PR08: commit metadata', 'status': 'failed',
             'reason': 'See check-practice.txt for the checker output.'}],
        'defect': {
            'reproducer': 'Replay the same bag with amcl-defect.yaml: chassis is absent, '
                          '10 diagnostic TF queries fail; see defect-launch.txt and tf.md.',
            'root_cause': 'base_frame_id=chassis breaks the lidar-to-base TF lookup. '
                          'The recorded robot frame is base_link.',
            'proof_after': f'base_link restores map -> odom: '
                           f'{metrics["tf_queries_successful"]}/{metrics["tf_queries_total"]} '
                           f'queries succeed; covariance median '
                           f'{metrics["median_xy_covariance_m2"]:.9f} m^2.'},
        'claims': {'public_tests_passed': True, 'defect_reproduced': True, 'defect_fixed': True},
        'time': {'contact_academic_hours': 2, 'self_study_hours': 2.5},
        'ai_used': True,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    checker = subprocess.run([sys.executable, '.course-kit/v1/tools/check_practice.py',
                              'PR08', '--submission', '.', '--json'], text=True, capture_output=True)
    (folder / 'check-practice.txt').write_text(checker.stdout + checker.stderr, encoding='utf-8')
    if checker.returncode == 0:
        report['tests'][-1] = {'name': 'check_practice.py PR08', 'status': 'passed'}
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(validation.stdout.strip())
    print(checker.stdout.strip())


if __name__ == '__main__':
    main()
