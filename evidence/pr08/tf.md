# TF: контролируемый отказ и восстановление

Оба опыта выполнены в существующем контейнере `practical_hofstadter`, ROS 2 Jazzy.
Карта, MCAP, начальная гипотеза `(0, 0, 0)` и обязательный профиль фиксированы.
Отличается только `base_frame_id`; процессам и буферам TF не даётся пережить опыт.

## Неизменные входы

- Course kit: `v1-w08`, SHA-256 архива
  `aea8efd0a51668af63f2e475b82bfa28bd76c21f20d8afea6b136d43a56a88fb`.
- `map.yaml`: `79d1003f551943d946a047295f100b1980c00415009b52e60cb9a9eaedf66cc0`.
- `map.pgm`: `f190d3ecdbeebe8e9ac476d02dfcc47d51014638b38ba7a1d8a3c604039549de`.
- MCAP: `ef9ea63a02dc9a2d25ac0060dc99977a70884cedb7ba9841de62f41f52ec1292`.
- Полная запись: `/clock` от 157.763 до 188.333 с,
  длительность 30.570 с.
- Путь по записанной одометрии: 5.346 м.
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
ros2 launch localization_case localization.launch.py \
  params_file:=$PWD/src/localization_case/config/amcl-defect.yaml \
  map:=$PWD/evidence/pr08/map.yaml
ros2 run localization_case measure_localization.py --ros-args \
  -p output:=evidence/pr08/defect.json
ros2 bag play fixtures/pr07-sensors --rate 0.5
ros2 run tf2_ros tf2_echo map odom --ros-args -p use_sim_time:=true
```

Первая сохранённая ошибка AMCL:

```text
[amcl-2] [ERROR] [1793000432.043408977] [amcl]: Couldn't transform from lidar_link to chassis, even though the message notifier is in use: ("chassis" passed to lookupTransform argument target_frame does not exist. )
```

Та же команда `tf2_echo` сообщает `Invalid frame ID "map" ... frame does not exist`.
В диагностике разгона выполнено 10 запросов `map → odom`,
успешных 0.
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

- Первый принятый `/clock`: 157.763 с.
- Последний принятый `/clock`: 188.333 с.
- Окно: [167.763; 187.763) с, разгон 10 с, оценка 20 с.
- Реальные TF-запросы: 200.
- Успешные: 200.
- Доступность: 100.0%, порог 95%.
- Сообщений `/amcl_pose` в том же окне: 66.
- Медиана `covariance[0] + covariance[7]`:
  0.034067669 м², порог 0,25 м².

Каждый запрос и stamp исходных поз сохранены в `localization.observations.json`.
Пропуски не заменялись повторными запросами к одному состоянию буфера.

## Временная согласованность и предел вывода

| Сообщение | Первый header.stamp, с | Последний header.stamp, с | `/clock` при приёме минус stamp, с |
| --- | --- | --- | --- |
| `/vehicle/odom` | 158.620 | 188.320 | -0.036 … 0.006 |
| `/vehicle/scan` | 158.700 | 188.200 | 0.034 … 0.067 |

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
