# -*- coding: utf-8 -*-
"""Генератор тестовых документов с вымышленными персональными данными."""
import csv, json
from pathlib import Path

HERE = Path(__file__).parent
TXT = """СЛУЖЕБНАЯ ЗАПИСКА № 47-К от 14.03.2024

Кому: Генеральному директору ООО «Ромашка» Кузнецову Ивану Петровичу
От: начальника отдела кадров Петровой Марии Сергеевны

Прошу оформить приём на работу Иванова Ивана Ивановича, 12.03.1985 г.р.,
паспорт 45 12 345678 выдан ОВД Пресненского района, СНИЛС 112-233-445 95,
ИНН 771234567890, зарегистрирован: 119991, г. Москва, ул. Ленина, д. 12, кв. 45.
Контакты: +7 (916) 123-45-67, iv.ivanov@example.ru, telegram @ivanov_ii.
Реквизиты для перечисления зарплаты: счёт 40702810900000012345, БИК 044525225.
Служебный автомобиль Х123УК799 закрепить за Ивановым.

Кузнецов подтвердил согласование устно. Петрова М.С. подготовит приказ.
"""
(HERE / "zapiska.txt").write_text(TXT, encoding="utf-8")
(HERE / "zapiska.md").write_text("# Служебная записка\n\n" + TXT, encoding="utf-8")

rows = [["ФИО", "Должность", "Телефон", "Email", "ИНН", "Адрес"],
        ["Иванов Иван Иванович", "инженер", "+7 916 123-45-67", "iv.ivanov@example.ru",
         "771234567890", "г. Москва, ул. Ленина, д. 12, кв. 45"],
        ["Петрова Мария Сергеевна", "кадровик", "8 495 111-22-33", "m.petrova@example.ru",
         "500100732259", "г. Химки, ул. Мира, д. 3, кв. 7"],
        ["Кузнецов Иван Петрович", "директор", "+7 903 555-01-02", "ceo@romashka.ru",
         "771234567890", "г. Москва, пр-т Мира, д. 101, оф. 5"]]
with (HERE / "sotrudniki.csv").open("w", encoding="utf-8", newline="") as fh:
    csv.writer(fh).writerows(rows)

(HERE / "zayavka.json").write_text(json.dumps({
    "id": 4417,
    "client": {"name": "Иванов Иван Иванович", "phone": "+7 916 123-45-67",
               "email": "iv.ivanov@example.ru", "passport": "45 12 345678"},
    "comment": "Перезвонить Иванову после 18:00, адрес доставки — г. Москва, ул. Ленина, д. 12, кв. 45",
    "amount": 15400,
}, ensure_ascii=False, indent=2), encoding="utf-8")

import openpyxl
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Сотрудники"
for r in rows: ws.append(r)
wb.save(HERE / "sotrudniki.xlsx")

import docx
d = docx.Document()
d.add_heading("Служебная записка № 47-К", level=1)
p = d.add_paragraph("Прошу оформить приём на работу ")
p.add_run("Иванова Ивана Ивановича").bold = True
p.add_run(", 12.03.1985 г.р., паспорт ")
p.add_run("45 12 345678").italic = True
p.add_run(", тел. +7 (916) 123-45-67, e-mail iv.ivanov@example.ru.")
d.add_paragraph("Согласовано: Кузнецов Иван Петрович, ООО «Ромашка», ИНН 771234567890.")
t = d.add_table(rows=1, cols=3); t.style = "Table Grid"
hdr = t.rows[0].cells
hdr[0].text = "ФИО"; hdr[1].text = "Телефон"; hdr[2].text = "Адрес"
row = t.add_row().cells
row[0].text = "Петрова Мария Сергеевна"; row[1].text = "8 495 111-22-33"
row[2].text = "119991, г. Москва, ул. Ленина, д. 12, кв. 45"
d.sections[0].footer.paragraphs[0].text = "Подготовила Петрова М.С., доб. 4417"
d.save(HERE / "zapiska.docx")

import fitz
doc = fitz.open(); page = doc.new_page()
page.insert_text((60, 80), "Sluzhebnaya zapiska", fontsize=14)
y = 120
for line in ["Ivanov Ivan Ivanovich, tel. +7 (916) 123-45-67",
             "email: iv.ivanov@example.ru, INN 771234567890",
             "Adres: 119991, Moscow, Lenina 12-45"]:
    page.insert_text((60, y), line, fontsize=11); y += 22
doc.save(HERE / "zapiska.pdf")

# --- документ со «структурным» содержимым (w:sdt) --------------------------
# Такие блоки создают Word-поля контента и конструкторы договоров. Обычный
# обход document.paragraphs их не видит — на этом терялась целая колонка
# реквизитов в настоящем договоре. Фикстура закрепляет регрессию.
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

d2 = docx.Document()
d2.add_heading("Договор № 7", level=1)
d2.add_paragraph("Заказчик: Смирнов Олег Игоревич, тел. +7 (495) 200-31-44.")

hidden = d2.add_paragraph(
    "Исполнитель: Белова Анна Сергеевна, ИНН 7701234560, "
    "адрес: 101000, г. Москва, ул. Полевая, д. 74, лит. А, пом. 12.")
body = d2.element.body
sdt = OxmlElement("w:sdt")
sdt.append(OxmlElement("w:sdtPr"))
content = OxmlElement("w:sdtContent")
body.remove(hidden._p)
content.append(hidden._p)
sdt.append(content)
sectPr = body.find(qn("w:sectPr"))
body.insert(list(body).index(sectPr) if sectPr is not None else len(body), sdt)
d2.save(HERE / "structured.docx")

(HERE / "pismo.html").write_text(
    "<html><head><meta charset='utf-8'><title>Письмо</title></head><body>"
    "<h1>Уведомление</h1><p>Уважаемый <b>Иванов Иван Иванович</b>, "
    "ваш заказ доставят по адресу: г. Москва, ул. Ленина, д. 12, кв. 45. "
    "Телефон курьера +7 916 123-45-67.</p>"
    "<script>var x='не трогать iv.ivanov@example.ru'</script></body></html>",
    encoding="utf-8")
print("готово:", ", ".join(sorted(p.name for p in HERE.iterdir() if p.name != "make_samples.py")))
