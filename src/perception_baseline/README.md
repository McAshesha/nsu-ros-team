# perception_baseline

Обёртка baseline-детектора ПР09. Нода `perception_node` принимает пару RGB/depth и публикует:

| Топик | Тип | Что внутри |
|---|---|---|
| `/perception/detections_2d` | `vision_msgs/msg/Detection2DArray` | bbox и класс `cone` для каждой красной области |
| `/perception/objects_3d` | `vision_msgs/msg/Detection3DArray` | точка в `camera_optical_frame`, только если глубина пригодна |
| `/perception/status` | `diagnostic_msgs/msg/DiagnosticArray` | причина: `ok`, `no_detections`, `missing_depth`, `zero_depth`, `stamp_mismatch`, `frame_mismatch`, `invalid_depth` |

Входы: `/camera/image_raw` (`rgb8`) и `/camera/depth/image_raw` (`16UC1`, мм), QoS sensor data. Пара принимается при одинаковом `header.stamp` и `frame_id = camera_optical_frame`. Если depth с тем же stamp не пришла за `depth_wait_s` (0.5 с), 2D публикуется, а 3D — нет.

Точка — пиксель `u = x + w // 2`, `v = y + h // 2` с глубиной `Z`, `X = (u - cx) Z / fx`, `Y = (v - cy) Z / fy`. Это точка поверхности на луче, а не центр объекта: `bbox.size` нулевой, размер и ориентация не оцениваются. `score = 1.0` только означает «найдено» — у baseline нет оценки уверенности.

Детектор и калибровка — неизменённые копии `baseline-detector.json` и `calibration.json` из `.course-kit/v1/fixtures/pr09`; алгоритм тот же, что `detect()` в `evaluate_perception.py` (проверяется тестом).

## Запуск

Из корня репозитория:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select perception_baseline
source install/setup.bash
ros2 run perception_baseline perception_node
```

Отправить пару из fixture (в другом терминале, тоже из корня репозитория):

```bash
ros2 run perception_baseline send_pair --ros-args -p sample:=sample-04
ros2 run perception_baseline send_pair --ros-args -p sample:=sample-04 -p depth_mode:=zero
ros2 run perception_baseline send_pair --ros-args -p sample:=sample-04 -p depth_mode:=none
ros2 run perception_baseline send_pair --ros-args -p sample:=sample-04 -p depth_mode:=stamp
ros2 run perception_baseline send_pair --ros-args -p sample:=sample-04 -p frame_id:=camera_link
```

Результат:

```bash
ros2 topic echo /perception/objects_3d
ros2 topic echo /perception/status
```

## Тесты

```bash
colcon test --packages-select perception_baseline --event-handlers console_direct+
colcon test-result --verbose
```

Тестам нужен распакованный course kit в `.course-kit/v1`.
