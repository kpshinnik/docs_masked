# -*- coding: utf-8 -*-
"""Адаптеры форматов: вытащить текстовые фрагменты, вернуть их обратно.

Контракт адаптера:
    read_units()  -> список строк в детерминированном порядке
    write_units() -> записать изменённые строки, сохранив структуру файла

Для DOCX/XLSX/CSV/JSON/HTML запись идёт «на место», с сохранением
форматирования. PDF читается, но пересобирается только через режим
редактирования (add_redact_annot) — обычная запись отдаёт .txt/.md.
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".log", ".tex", ".yaml", ".yml", ".ini", ".srt"}


class UnsupportedFormat(RuntimeError):
    pass


class DocumentAdapter(ABC):
    suffixes: tuple[str, ...] = ()
    writeback: bool = True

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @abstractmethod
    def read_units(self) -> list[str]: ...

    @abstractmethod
    def write_units(self, units: list[str], out_path: Path) -> Path: ...

    def read_contexts(self) -> list[str]:
        """Подсказки к фрагментам: заголовок колонки или предыдущий фрагмент.

        В таблицах и вёрстке подпись и значение часто лежат в разных ячейках:
        «ИНН/КПП:» в одной, «7700000000 / 770000001» в другой. Без подсказки
        второй фрагмент — просто набор цифр.
        """
        out: list[str] = []
        prev = ""
        for unit in self.read_units():
            out.append(prev if len(unit) <= 80 else "")
            if unit.strip():
                prev = unit.strip()[-80:]
        return out

    def plain_text(self) -> str:
        return "\n".join(self.read_units())

    def default_out(self, suffix_tag: str = ".masked") -> Path:
        return self.path.with_name(self.path.stem + suffix_tag + self.path.suffix)


# ------------------------------------------------------------------ txt / md


class PlainTextAdapter(DocumentAdapter):
    suffixes = tuple(TEXT_SUFFIXES)

    def read_units(self) -> list[str]:
        return [self.path.read_text(encoding=self._encoding())]

    def _encoding(self) -> str:
        raw = self.path.read_bytes()
        try:
            raw.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            try:
                from charset_normalizer import from_bytes
                best = from_bytes(raw).best()
                if best:
                    return best.encoding
            except Exception:
                pass
            return "cp1251"

    def write_units(self, units: list[str], out_path: Path) -> Path:
        out_path.write_text(units[0], encoding="utf-8")
        return out_path


# ------------------------------------------------------------------ html


class HtmlAdapter(DocumentAdapter):
    suffixes = (".html", ".htm", ".xhtml")

    def __init__(self, path):
        super().__init__(path)
        from bs4 import BeautifulSoup
        self._soup = BeautifulSoup(self.path.read_text(encoding="utf-8", errors="replace"),
                                   "html.parser")
        self._nodes = [n for n in self._soup.find_all(string=True)
                       if n.parent.name not in ("script", "style") and str(n).strip()]

    def read_units(self) -> list[str]:
        return [str(n) for n in self._nodes]

    def write_units(self, units: list[str], out_path: Path) -> Path:
        for node, new in zip(self._nodes, units):
            if str(node) != new:
                node.replace_with(new)
        out_path.write_text(str(self._soup), encoding="utf-8")
        return out_path


# ------------------------------------------------------------------ json


class JsonAdapter(DocumentAdapter):
    suffixes = (".json",)

    def __init__(self, path):
        super().__init__(path)
        self._data = json.loads(self.path.read_text(encoding="utf-8"))
        self._paths: list[list[Any]] = []
        self._collect(self._data, [])

    def _collect(self, node: Any, trail: list[Any]) -> None:
        if isinstance(node, str):
            self._paths.append(list(trail))
        elif isinstance(node, dict):
            for k, v in node.items():
                self._collect(v, trail + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._collect(v, trail + [i])

    def _get(self, trail: list[Any]) -> Any:
        node = self._data
        for step in trail:
            node = node[step]
        return node

    def _set(self, trail: list[Any], value: str) -> None:
        if not trail:
            self._data = value
            return
        node = self._data
        for step in trail[:-1]:
            node = node[step]
        node[trail[-1]] = value

    def read_units(self) -> list[str]:
        return [self._get(p) for p in self._paths]

    def write_units(self, units: list[str], out_path: Path) -> Path:
        for trail, new in zip(self._paths, units):
            self._set(trail, new)
        out_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path


# ------------------------------------------------------------------ csv / tsv


class CsvAdapter(DocumentAdapter):
    suffixes = (".csv", ".tsv")

    def __init__(self, path):
        super().__init__(path)
        text = self.path.read_text(encoding="utf-8-sig", errors="replace")
        delim = "\t" if self.path.suffix == ".tsv" else self._sniff(text)
        self._delim = delim
        self._rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        self._shape = [len(r) for r in self._rows]

    @staticmethod
    def _sniff(text: str) -> str:
        try:
            return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            return ";" if text[:2048].count(";") > text[:2048].count(",") else ","

    def read_units(self) -> list[str]:
        return [cell for row in self._rows for cell in row]

    def read_contexts(self) -> list[str]:
        header = self._rows[0] if self._rows else []
        return [header[i] if i < len(header) else ""
                for row in self._rows for i in range(len(row))]

    def write_units(self, units: list[str], out_path: Path) -> Path:
        it = iter(units)
        rows = [[next(it) for _ in range(n)] for n in self._shape]
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh, delimiter=self._delim).writerows(rows)
        return out_path


# ------------------------------------------------------------------ xlsx


class XlsxAdapter(DocumentAdapter):
    suffixes = (".xlsx", ".xlsm")

    def __init__(self, path):
        super().__init__(path)
        import openpyxl
        self._wb = openpyxl.load_workbook(self.path)
        self._cells = [c for ws in self._wb.worksheets for row in ws.iter_rows()
                       for c in row if c.value is not None]

    def read_units(self) -> list[str]:
        return [str(c.value) for c in self._cells]

    def read_contexts(self) -> list[str]:
        headers: dict[tuple[str, int], str] = {}
        for ws in self._wb.worksheets:
            for c in next(ws.iter_rows(min_row=1, max_row=1), ()):
                if c.value is not None:
                    headers[(ws.title, c.column)] = str(c.value)
        return ["" if c.row == 1 else headers.get((c.parent.title, c.column), "")
                for c in self._cells]

    def write_units(self, units: list[str], out_path: Path) -> Path:
        for cell, new in zip(self._cells, units):
            if str(cell.value) != new:
                cell.value = new
        self._wb.save(out_path)
        return out_path


# ------------------------------------------------------------------ docx


def _docx_paragraphs(doc):
    """Все абзацы документа в порядке следования — обходом XML, а не модели.

    document.paragraphs / table.rows не видят абзацы внутри структурных
    элементов: w:sdt (поля контента), w:txbxContent (надписи), альтернативного
    содержимого. На настоящем договоре из-за этого терялась целая колонка
    реквизитов. Обход по w:p через lxml находит их все и ровно по одному разу
    (в отличие от row.cells, который дублирует объединённые ячейки).
    """
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    def walk(part, parent):
        element = getattr(part, "element", None)
        if element is None:
            return
        for node in element.iter(qn("w:p")):
            yield Paragraph(node, parent)

    yield from walk(doc, doc)
    for section in doc.sections:
        for part in (section.header, section.footer,
                     section.even_page_header, section.even_page_footer,
                     section.first_page_header, section.first_page_footer):
            if part is not None:
                yield from walk(part, part)


def _apply_ops_to_runs(paragraph, old: str, new: str) -> None:
    """Перенести посимвольную правку old->new на runs, сохранив форматирование."""
    runs = list(paragraph.runs)
    if not runs:
        return
    table: list[tuple[int, int, Any]] = []
    pos = 0
    for r in runs:
        length = len(r.text)
        table.append((pos, pos + length, r))
        pos += length
    ops = [op for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
           if op[0] != "equal"]
    for tag, i1, i2, j1, j2 in reversed(ops):
        repl = new[j1:j2]
        placed = False
        for s, e, run in table:
            if e <= i1 or s >= i2:
                continue
            ls, le = max(i1, s) - s, min(i2, e) - s
            if not placed:
                run.text = run.text[:ls] + repl + run.text[le:]
                placed = True
            else:
                run.text = run.text[:ls] + run.text[le:]
        if not placed:  # чистая вставка на стыке runs
            for s, e, run in table:
                if s <= i1 <= e:
                    run.text = run.text[:i1 - s] + repl + run.text[i1 - s:]
                    break


class DocxAdapter(DocumentAdapter):
    suffixes = (".docx",)

    def __init__(self, path):
        super().__init__(path)
        import docx
        self._doc = docx.Document(str(self.path))
        self._paras = list(_docx_paragraphs(self._doc))

    def read_units(self) -> list[str]:
        return [p.text for p in self._paras]

    def write_units(self, units: list[str], out_path: Path) -> Path:
        for para, new in zip(self._paras, units):
            old = para.text
            if old != new:
                _apply_ops_to_runs(para, old, new)
        self._doc.save(str(out_path))
        return out_path


# ------------------------------------------------------------------ pdf


class PdfAdapter(DocumentAdapter):
    suffixes = (".pdf",)
    writeback = False

    def __init__(self, path):
        super().__init__(path)
        import fitz
        self._fitz = fitz
        self._doc = fitz.open(str(self.path))

    def read_units(self) -> list[str]:
        return [page.get_text("text") for page in self._doc]

    def plain_text(self) -> str:
        parts = []
        for i, page in enumerate(self._doc, 1):
            parts.append(f"\n\n--- страница {i} ---\n{page.get_text('text')}")
        return "".join(parts).strip()

    def write_units(self, units: list[str], out_path: Path) -> Path:
        """PDF не пересобирается — сохраняем замаскированный текст рядом."""
        target = out_path.with_suffix(".txt") if out_path.suffix.lower() == ".pdf" else out_path
        target.write_text("\n\n".join(units), encoding="utf-8")
        return target

    def redact(self, replacements: list[tuple[str, str]], out_path: Path) -> Path:
        """Настоящее вымарывание: текст физически удаляется из PDF."""
        for page in self._doc:
            for original, tag in replacements:
                original = original.strip()
                if len(original) < 3:
                    continue
                for rect in page.search_for(original, quads=False):
                    page.add_redact_annot(rect, text=tag, fontsize=8,
                                          fill=(0.94, 0.94, 0.94))
            page.apply_redactions()
        self._doc.save(str(out_path), garbage=4, deflate=True)
        return out_path


# ------------------------------------------------------------- rtf/doc (macOS)


class TextutilAdapter(DocumentAdapter):
    """.rtf / .doc через системный textutil (только чтение)."""
    suffixes = (".rtf", ".doc", ".odt", ".wordml")
    writeback = False

    def read_units(self) -> list[str]:
        if not shutil.which("textutil"):
            raise UnsupportedFormat(
                f"{self.path.suffix}: нужен textutil (macOS) или конвертация в .docx")
        res = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(self.path)],
                             capture_output=True, check=True)
        return [res.stdout.decode("utf-8", errors="replace")]

    def write_units(self, units: list[str], out_path: Path) -> Path:
        target = out_path.with_suffix(".txt")
        target.write_text(units[0], encoding="utf-8")
        return target


# ------------------------------------------------------------------ фабрика

_ADAPTERS: tuple[type[DocumentAdapter], ...] = (
    DocxAdapter, XlsxAdapter, PdfAdapter, CsvAdapter, JsonAdapter,
    HtmlAdapter, TextutilAdapter, PlainTextAdapter,
)


def open_document(path: str | Path) -> DocumentAdapter:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    for cls in _ADAPTERS:
        if suffix in cls.suffixes:
            return cls(p)
    # неизвестное расширение: пробуем как текст, если файл декодируется
    try:
        p.read_text(encoding="utf-8")
        return PlainTextAdapter(p)
    except UnicodeDecodeError as exc:
        raise UnsupportedFormat(
            f"не умею читать {suffix or 'файл без расширения'}: {p.name}. "
            "Поддержано: txt/md/html/json/csv/tsv/xlsx/docx/pdf/rtf/doc") from exc


def supported_formats() -> list[str]:
    out: list[str] = []
    for cls in _ADAPTERS:
        out.extend(cls.suffixes)
    return sorted(set(out))
