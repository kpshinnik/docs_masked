# Python API

```python
import sys; sys.path.insert(0, "/путь/к/docs_masked")   # если не ставили пакет
from pii_shield import mask_text, unmask_text, assert_clean
```

## Быстрые функции

| Функция | Назначение |
|---|---|
| `mask_text(text, vault=None, cfg=None) -> MaskResult` | Маскирование строки. `MaskResult` содержит `.text`, `.spans`, `.vault`. |
| `mask_units(units, vault=None, cfg=None, contexts=None)` | Маскирование списка фрагментов общим сейфом: абзацы, ячейки таблицы. |
| `unmask_text(text, vault, mode="canonical", state=None)` | Обратная подстановка. Возвращает `(текст, список неизвестных тегов)`. |
| `verify(text, cfg=None, paranoid=True) -> list[Finding]` | Что осталось в тексте. Пустой список — можно отправлять. |
| `assert_clean(text, cfg=None)` | То же, но бросает `LeakGuardError`. Ставится перед любой отправкой. |
| `find_spans(text, cfg=None) -> list[Span]` | Найденные фрагменты без замены. |

## Работа с файлами

| Функция | Назначение |
|---|---|
| `mask_document(path, out=None, cfg=None, vault_path=None, passphrase=None, write=True, pdf_redact=False) -> MaskReport` | Обезличить файл любого поддерживаемого формата. |
| `unmask_document(path, vault_path, out=None, mode="sequential", passphrase=None)` | Восстановить файл. |
| `ask_document(path, instruction, provider="anthropic", ...) -> AskResult` | Полный круг с обращением к модели. |

`MaskReport` содержит `.masked_path`, `.vault_path`, `.vault`, `.spans`,
`.masked_units`, `.masked_text`, `.residual` и свойство `.clean`.

`AskResult` содержит `.answer` (уже восстановленный), `.answer_masked`,
`.report`, `.response`, `.unknown_tags`.

## Настройка

```python
from pii_shield import MaskConfig, mask_document

cfg = MaskConfig(
    style="bracket",                     # [[PERSON_1]] вместо #PERSON_1#
    custom_terms=["Проект Феникс", "SKU-778"],
    allowlist=["ООО «Ромашка»"],         # свою компанию скрывать не надо
    aggressive_names=True,
)
cfg.enable("DATE")                       # скрывать все даты
cfg.disable("ORG")                       # организации не трогать

report = mask_document("анкета.pdf", cfg=cfg)
```

Один и тот же `cfg` можно переиспользовать между фрагментами документа: он
хранит общий индекс персон, благодаря которому одиночная «Кузнецову» в одной
ячейке склеивается с «Кузнецов Иван Петрович» в другой.

## Сейф

```python
from pii_shield import Vault

vault = report.vault
vault.stats()                             # {'PERSON': 3, 'PHONE': 2, ...}
vault.canonical_of("PERSON", 1)           # форма для подстановки в новый текст
vault.entities["PERSON_1"].variants       # все встреченные словоформы
vault.save("сейф.json", passphrase="…")   # scrypt + Fernet, права 0600
Vault.load("сейф.json", passphrase="…")
```

`Entity.canonical` — самая полная встреченная форма, `Entity.nominative` —
реконструированный именительный падеж для ФИО. Подстановка в ответ модели
берёт `nominative`, если он есть.

## Свои детекторы

```python
import re
from pii_shield.detectors import detector, Span

@detector("employee_id")
def d_employee_id(text):
    for m in re.finditer(r"\bEMP-\d{6}\b", text):
        yield Span(m.start(), m.end(), "CUSTOM", m.group(0), priority=95)
```

Приоритет решает конфликты перекрытий: чем выше, тем сильнее детектор.
Диапазоны: 90+ — подтверждённые контрольной суммой или ключевым словом,
80–89 — устойчивые форматы, 70–79 — эвристики, ниже 30 — выключенные
по умолчанию метки.

## Единственная точка выхода в сеть

```python
from pii_shield import llm

resp = llm.send(masked_text, "инструкция", provider="anthropic")
```

`llm.send()` обязана вызвать `assert_clean()` до сетевого запроса. Если
добавляете провайдера — добавляйте внутрь `llm.py`, а не мимо него, иначе
теряется единственная гарантия, ради которой всё это существует.
