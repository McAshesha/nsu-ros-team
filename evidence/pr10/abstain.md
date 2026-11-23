# ПР10: отказ адаптера и коллизия кэша

## Параметры

Из `config/vlm.yaml`:

- `abstain_threshold: 0.5` — ответ с `confidence < 0.5` не публикуется как valid;
- `max_age_s: 0.25` — возраст `now_s - stamp_s` должен быть в `[0, 0.25]` с.

Значения взяты из `fixtures/vlm/README.md` комплекта. Время одно: в unit-тестах `now_s` передаётся явно, в ноде `use_sim_time: true` и возраст считается по `/clock`. `stamp_s` из mock и кэша не заменяется текущим временем.

Порядок проверки в `contract.evaluate`: JSON → схема (лишние поля, типы, enum, диапазоны) → возраст → уверенность. Любой отказ даёт канонический unknown: категории `unknown`, расстояния `null`, `confidence 0`, метка и frame исходного наблюдения сохраняются.

## Ожидаемая причина для каждого отказа

| Вход | now_s | status | status_reason |
|---|---:|---|---|
| `scene-clear.json` | 0.1 | valid | `""` |
| `scene-low-confidence.json` (confidence 0.24) | 0.1 | unknown | `low_confidence` |
| `scene-stale.json` (stamp_s 1.0) | 2.0 | unknown | `stale_input` |
| `scene-extra-command.json` (поле `drive`) | 0.1 | unknown | `invalid_schema` |
| не JSON, не объект, неизвестный enum | — | unknown | `invalid_schema` |
| метка из будущего (возраст < 0) | — | unknown | `stale_input` |

Все четыре строки для fixtures получены и в `schema-check.txt`, и в тестах (`tests.txt`), и в ROS-проверке (`ros-live.txt`).

## Дефект: prompt не входит в ключ кэша

Коммит `93f4dea`: в `cache_key` из payload убран `prompt_sha256`. Остальные части ключа (`image_sha256`, `model_id`, `generation_config`, `schema_version`) на месте.

Тесты на этом коммите:

```
FAILED test/test_cache.py::test_each_input_change_is_cache_miss[prompt]
  AssertionError: изменение prompt не дало промаха кэша
  assert 1 == 2   (backend.calls)
FAILED test/test_cache.py::test_each_key_component_changes_key[prompt_sha256-8240611528...]
  '0d59dd839c5db506...' != '0d59dd839c5db506...'
2 failed, 12 deselected
```

Сценарий в режиме `cache` с локальным backend (без сети): тот же кадр, тот же `model_id` и `generation_config`, во второй раз к файлу промпта добавлена строка `Use metric units.`, а backend для нового промпта отвечает `red`.

```
1) промпт A sha256=9c7dc248d7ee… ключ=0d59dd839c5db506… -> traffic_light=green, вызовов backend=1
2) промпт B sha256=1d8a111ec447… ключ=0d59dd839c5db506… -> traffic_light=green, вызовов backend=1
   ключи совпали ; backend для промпта B ответил бы red
```

Наблюдаемая коллизия: разные промпты дали один ключ `0d59dd83…`, второй запрос не дошёл до модели, и адаптер выдал старый ответ `green` как valid. Проверка схемы, возраста и уверенности это не ловит: сохранённый ответ сам по себе корректный, просто он на другой вопрос.

## Исправление

Коммит `1e2e439`: `prompt_sha256` возвращён в ключ. Хэш считается от фактически прочитанного файла промпта при каждом запросе.

```
1) промпт A sha256=9c7dc248d7ee… ключ=c1fa013acd4cc2ff… -> traffic_light=green, вызовов backend=1
2) промпт B sha256=1d8a111ec447… ключ=6124820a93ef7193… -> traffic_light=red, вызовов backend=2
   ключи разные ; backend для промпта B ответил бы red
```

Оба упавших теста проходят, всего `62 passed, 1 skipped` (`tests.txt`). Отдельно проверено, что изменение каждой из пяти частей ключа меняет ключ, а порядок полей в `generation_config` — нет.
