# scene_adapter

Нода `scene_adapter` превращает ответ VLM в `robotics_course_interfaces/msg/SceneDescription` и публикует его на `/perception/scene`. Свободный текст модели дальше адаптера не уходит: публикуется только проверенный контракт SceneDescription v1.

Режимы (`mode`):

- `mock` — читает `fixture_path`, публикует раз в 0.2 с по steady-таймеру, возраст считает по ROS-часам;
- `cache` — на каждый кадр `/camera/image_raw` ищет сохранённый сырой ответ по ключу; при промахе вызывает внедрённый backend и сохраняет ответ;
- `live` — без явно настроенного backend нода не запускается и пишет понятную ошибку; сетевого клиента в пакете нет.

Ключ кэша — SHA-256 от JSON с отсортированными ключами и без пробелов. В него входят `image_sha256`, `prompt_sha256` фактически прочитанного файла промпта, `model_id`, весь `generation_config` и `schema_version: 1`.

До публикации ответ проверяется по JSON Schema (лишние поля, типы, enum, диапазоны, `version`), затем по возрасту `now_s - stamp_s` (`max_age_s`) и уверенности (`abstain_threshold`). Отказ даёт канонический unknown: категории `unknown`, расстояния `null`, `confidence 0`, причина `invalid_schema`, `stale_input` или `low_confidence`, метка и frame исходного наблюдения сохраняются. Ответ с полем `drive` отклоняется целиком.

## Происхождение входов

Скопированы без изменений из course kit `v1-w11` (архив SHA-256 `0b67bfd41448549d21122124b7f49211ba2cd068cc56751871f319eadeb9d0ab`):

| Файл в репозитории | Источник в kit | SHA-256 |
|---|---|---|
| `src/robotics_course_interfaces/msg/SceneDescription.msg` | `interfaces/msg/SceneDescription.msg` | `ff1e901eed35bbb578809b68ef3384eae1df48e7fbedaff0c1fec628367c592a` |
| `contracts/scene-description-v1.schema.json` | `contracts/scene-description-v1.schema.json` | `f1d169aeabb2ed72dc6015201a09dd53e30ddfd1dcd55f0a3a20f9e540e1bda7` |
| `fixtures/vlm/scene-clear.json` | `fixtures/vlm/scene-clear.json` | `5b84b95eb5e93b18b1890d86641a11c991dfbe8bca18fe0f39bbb48dbf0f213f` |
| `fixtures/vlm/scene-low-confidence.json` | `fixtures/vlm/scene-low-confidence.json` | `ca5c7375303547a74b636645478ea59b5d68d1b46d26e6b8265992ae0153688c` |
| `fixtures/vlm/scene-stale.json` | `fixtures/vlm/scene-stale.json` | `2520f75cf581f95cf183baa8e4ce781dddb2c06c157b34cedf1bb800e252462f` |
| `fixtures/vlm/scene-extra-command.json` | `fixtures/vlm/scene-extra-command.json` | `77d65a92e5ea10f9f49d04537a7b1b1ad5cbf4d578dd70425d5774f4046723a0` |
| `fixtures/vlm/README.md` | `fixtures/vlm/README.md` | `1e7891c06c1bf9904888400a8290c3d118ef0795e796a1eef3db02491fd3109d` |

`config/vlm.yaml` и `config/scene-prompt.txt` написаны для этого пакета.

## Запуск

Из корня репозитория (пути в `config/vlm.yaml` относительные):

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to scene_adapter
source install/setup.bash
ros2 run scene_adapter scene_adapter --ros-args --params-file config/vlm.yaml
```

В конфигурации `use_sim_time: true`, поэтому нужен `/clock`, например:

```bash
ros2 topic pub /clock rosgraph_msgs/msg/Clock "{clock: {sec: 0, nanosec: 100000000}}"
ros2 topic echo /perception/scene --once
```

Другой fixture: `-p fixture_path:=fixtures/vlm/scene-stale.json` (при `/clock` = 2.0 с ожидается `stale_input`).

## Тесты

```bash
colcon test --packages-select scene_adapter --event-handlers console_direct+
colcon test-result --verbose
```

Тесты не обращаются к сети: в cache-тестах внедрён локальный backend, который возвращает сырой fixture и считает вызовы; любое сетевое соединение из Python в этих тестах завершает тест ошибкой.
