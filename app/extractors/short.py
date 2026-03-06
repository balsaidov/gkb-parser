"""Парсер краткой формы отчёта ГКБ (gkb_short).

Краткая форма содержит:
- Персональные данные (ФИО, телефоны, адреса)
- Документы удостоверения личности (таблица)
- Общая сумма задолженности + кол-во обязательств
- Сводная таблица обязательств по кредиторам
"""
import re
import io
from typing import Optional

import pdfplumber

from app.models import (
    GkbReport, Obligation, Address, IdentityDocument,
)
from app.extractors.personal import (
    _clean, _extract, _extract_col, _extract_int, _extract_float,
)


def _parse_short_personal(text: str) -> dict:
    """Извлечь персональные данные из краткой справки."""
    data = {}

    # ФИО
    data["last_name"] = _extract_col(text, r"Фамилия:[ \t]*([^\n]+)")
    data["first_name"] = _extract_col(text, r"Имя:[ \t]*([^\n]+)")
    data["middle_name"] = _extract_col(text, r"Отчество:[ \t]*([^\n]+)")

    # client_name из "Получатель:" или собрать из ФИО
    recipient = _extract_col(text, r"Получатель:[ \t]*([^\n]+)")
    if recipient:
        data["client_name"] = recipient
    else:
        parts = [p for p in [data.get("last_name"), data.get("first_name"),
                             data.get("middle_name")] if p]
        data["client_name"] = " ".join(parts) if parts else "Неизвестно"

    # Дата рождения, гражданство, пол
    data["birth_date"] = _extract(text, r"Дата рождения:\s*([\d.]+)")
    data["citizenship"] = _extract_col(text, r"Гражданство:\s*(.+)")
    data["gender"] = _extract_col(text, r"Пол:\s*(.+)")

    # Контакты
    data["phone_mobile"] = _extract_col(text, r"Моб\.\s*тел\.:\s*(.+)")
    data["phone_work"] = _extract_col(text, r"Раб\.?\s*тел\.:\s*(.+)")
    data["phone_home"] = _extract_col(text, r"Дом\.?\s*тел\.:\s*(.+)")
    data["email"] = _extract_col(text, r"E-mail:\s*(.+)")

    # Метаданные отчёта
    data["report_date"] = _extract(text, r"Дата выдачи:\s*([\d.]+)")
    data["report_time"] = _extract(text, r"Время выдачи:\s*([\d:]+)")
    data["report_number"] = _extract_int(text, r"Номер кредитного отчета:\s*(\d+)")
    data["report_type"] = _extract_col(text, r"Вид кредитного отчета:\s*(.+)")

    # ИИН — в краткой форме нет поля "ИИН:" на первой странице,
    # извлекаем из таблицы документов
    iin = _extract(text, r"ИИН\s+(\d{12})")
    if iin:
        data["iin"] = iin

    return {k: v for k, v in data.items() if v is not None}


def _extract_right_column(line: str, min_col: int = 50) -> str:
    """Извлечь текст из правой колонки строки (позиция min_col+).

    В двухколоночном layout левая колонка (персональные данные) и
    правая колонка (адрес) находятся на одной строке. Правая колонка
    начинается примерно с позиции 60-70.
    """
    if len(line) <= min_col:
        # Строка короче правой колонки — скорее всего чисто левая колонка
        return ""
    # Ищем начало правой колонки: первый непробельный символ после min_col
    right_part = line[min_col:]
    return right_part.strip()


def _extract_address_short(text: str, address_type: str) -> Optional[Address]:
    """Извлечь адрес из краткой справки с двухколоночным layout.

    В краткой справке адресные блоки расположены в правой колонке
    (отступ ~60+ символов). Левая колонка содержит персональные данные,
    которые нужно отфильтровать при парсинге многострочных полей.
    """
    # Найти блок адреса
    if address_type == "Постоянное место жительства":
        pattern = rf"{address_type}\s*(.*?)(?:Место прописки|Примечание)"
    else:
        pattern = rf"{address_type}\s*(.*?)(?:Примечание|Текущая информация)"

    m = re.search(pattern, text, re.DOTALL)
    if not m:
        pattern = rf"{address_type}\s*(.*?)(?=\n\s*\n\s*\n)"
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            return None

    block = m.group(0)

    addr = Address()
    addr.country = _extract_col(block, r"Страна:\s*(.+)")
    addr.region = _extract_col(block, r"Область:\s*(.+)")
    addr.district = _extract_col(block, r"Район:\s*(.+)")
    addr.city = _extract_col(block, r"Город:\s*(.+)")
    addr.house_apartment = _extract_col(block, r"Дом,\s*кв:\s*(.+)")
    addr.postal_code = _extract_col(block, r"Почтовый индекс:\s*(.+)")

    # Улица — может быть многострочной, до "Дом, кв:"
    # Нужно собрать все строки правой колонки между "Улица:" и "Дом, кв:"
    street_match = re.search(r"Улица:\s*(.+?)(?=Дом,\s*кв:)", block, re.DOTALL)
    if street_match:
        raw_street = street_match.group(1)
        lines = raw_street.split("\n")
        street_parts = []

        for i, line in enumerate(lines):
            if i == 0:
                # Первая строка — текст после "Улица:" на той же строке
                stripped = line.strip()
                if stripped:
                    # Обрезаем по границе колонки (2+ пробелам)
                    stripped = re.split(r"\s{2,}", stripped)[0]
                    street_parts.append(stripped)
            else:
                # Последующие строки — берём только правую колонку
                # (чтобы отфильтровать "Гражданство:", "Пол:" из левой)
                right = _extract_right_column(line, min_col=50)
                if right:
                    # Убираем возможные метки правой колонки
                    right = re.split(r"\s{2,}", right)[0]
                    street_parts.append(right)

        street = " ".join(street_parts).strip()
        street = re.sub(r"\s{2,}", " ", street)
        addr.street = _clean(street)

    return addr


def _parse_short_documents(text: str, pdf_bytes: bytes) -> list[IdentityDocument]:
    """Извлечь документы удостоверения личности из краткой справки.

    Используем pdfplumber для извлечения таблицы документов,
    так как текстовый layout слишком сложен для regex.
    Fallback на regex если pdfplumber не нашёл таблицу.
    """
    docs = []

    # Попробуем pdfplumber для таблицы документов
    try:
        docs = _parse_documents_pdfplumber(pdf_bytes)
        if docs:
            return docs
    except Exception:
        pass

    # Fallback: regex-парсинг
    return _parse_documents_regex(text)


def _parse_documents_pdfplumber(pdf_bytes: bytes) -> list[IdentityDocument]:
    """Извлечь документы через pdfplumber tables."""
    docs = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if "удостоверяющих личность" not in page_text.lower():
                continue

            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                for row in table:
                    if not row or len(row) < 4:
                        continue
                    # Пропускаем строки заголовков
                    cells = [str(c).strip() if c else "" for c in row]
                    if "Вид документа" in cells[0] or "Номер" in cells[0]:
                        continue
                    if not any(cells):
                        continue

                    doc_type = _clean(cells[0]) if len(cells) > 0 else None
                    number = _clean(cells[1]) if len(cells) > 1 else None
                    issue_date = _clean(cells[2]) if len(cells) > 2 else None
                    expiry = _clean(cells[3]) if len(cells) > 3 else None
                    full_name = _clean(cells[4]) if len(cells) > 4 else None
                    bureau_date = _clean(cells[5]) if len(cells) > 5 else None

                    if number or doc_type:
                        doc = IdentityDocument(
                            type=doc_type,
                            number=number,
                            issue_date=issue_date,
                            expiry_date=expiry,
                            full_name=full_name,
                            bureau_received_date=bureau_date,
                        )
                        docs.append(doc)

    return docs


def _parse_documents_regex(text: str) -> list[IdentityDocument]:
    """Fallback парсинг документов через regex."""
    docs = []

    # Найти блок таблицы документов
    block_match = re.search(
        r"удостоверяющих личность:(.*?)(?:Страница\s+\d|ОБЩАЯ ИНФОРМАЦИЯ|В данном блоке содержится)",
        text,
        re.DOTALL,
    )
    if not block_match:
        return docs

    block = block_match.group(1)

    # Ищем ИИН — всегда 12 цифр
    iin_match = re.search(r"ИИН\s+(\d{12})", block)
    if iin_match:
        # Ищем дату бюро на строке с ИИН или рядом
        iin_line_match = re.search(
            r"ИИН\s+(\d{12})\s+(Нет данных|[\d.]+)\s+(Нет данных|[\d.]+)\s+(.+?)\s{2,}([\d.]+)",
            block,
        )
        if iin_line_match:
            docs.append(IdentityDocument(
                type="ИИН",
                number=iin_line_match.group(1),
                issue_date=_clean(iin_line_match.group(2)),
                expiry_date=_clean(iin_line_match.group(3)),
                full_name=iin_line_match.group(4).strip(),
                bureau_received_date=_clean(iin_line_match.group(5)),
            ))
        else:
            docs.append(IdentityDocument(
                type="ИИН",
                number=iin_match.group(1),
            ))

    # Ищем Удостоверение личности — номер 9 цифр
    ud_match = re.search(
        r"Удостоверение.*?(\d{9})\s+([\d.]+|Нет данных)\s+([\d.]+|Нет данных)",
        block,
        re.DOTALL,
    )
    if ud_match:
        docs.append(IdentityDocument(
            type="Удостоверение личности",
            number=ud_match.group(1),
            issue_date=_clean(ud_match.group(2)),
            expiry_date=_clean(ud_match.group(3)),
        ))

    # Ищем Паспорт гражданина — номер N\d+
    passport_match = re.search(
        r"Паспорт гражданина.*?([A-ZА-Я]?\d{7,})\s+([\d.]+|Нет данных)\s+([\d.]+|Нет данных)",
        block,
        re.DOTALL,
    )
    if passport_match:
        docs.append(IdentityDocument(
            type="Паспорт гражданина",
            number=passport_match.group(1),
            issue_date=_clean(passport_match.group(2)),
            expiry_date=_clean(passport_match.group(3)),
        ))

    # Ищем РНН
    rnn_match = re.search(
        r"РНН\s+(\d+)\s+([\d.]+|Нет данных)\s+([\d.]+|Нет данных)",
        block,
    )
    if rnn_match:
        docs.append(IdentityDocument(
            type="РНН",
            number=rnn_match.group(1),
            issue_date=_clean(rnn_match.group(2)),
            expiry_date=_clean(rnn_match.group(3)),
        ))

    # Ищем Уникальный номер финансового мониторинга
    ufm_match = re.search(
        r"Уникальный номер.*?финансового.*?(\d[\d.]+)\s+([\d.]+|Нет данных)",
        block,
        re.DOTALL,
    )
    if ufm_match:
        docs.append(IdentityDocument(
            type="Уникальный номер финансового мониторинга",
            number=ufm_match.group(1),
            issue_date=_clean(ufm_match.group(2)),
        ))

    return docs


def _parse_kzt_amount(text: str) -> Optional[float]:
    """Распарсить сумму в KZT: '397905.06 KZT' -> 397905.06"""
    if not text:
        return None
    text = text.strip()
    text = text.replace("KZT", "").replace(" ", "").replace(",", ".").strip()
    if not text or text.lower() in ("нет данных", "-", "нет"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fix_creditor_spacing(raw: str) -> str:
    """Исправить пропущенные пробелы в имени кредитора из pdfplumber.

    pdfplumber иногда склеивает слова (например АО"KaspiBank" вместо АО "Kaspi Bank").
    Добавляем пробелы по типовым паттернам.
    """
    s = raw
    # Пробел перед открывающей кавычкой после буквы/цифры
    s = re.sub(r'([А-ЯЁа-яёA-Za-z0-9])([«""])', r'\1 \2', s)
    # Пробел после открывающей кавычки перед буквой (если нет)
    s = re.sub(r'([«""])([А-ЯЁа-яёA-Za-z])', r'\1\2', s)  # keep as is - no extra space after opening quote
    # Пробел после закрывающей кавычки перед буквой
    s = re.sub(r'([»""])([А-ЯЁA-Za-z(])', r'\1 \2', s)
    # Пробел между строчной кириллицей и заглавной кириллицей (КасписБанк → Каспис Банк)
    s = re.sub(r'([а-яё])([А-ЯЁ])', r'\1 \2', s)
    # Пробел между строчной латиницей и заглавной латиницей (CityBank → City Bank)
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    # Пробел между закрывающей скобкой и буквой
    s = re.sub(r'(\))([А-ЯЁA-Za-zа-яё])', r'\1 \2', s)
    # Убираем двойные пробелы
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip()


def _find_creditor_in_text(block: str, contract: str) -> str:
    """Найти имя кредитора по номеру договора в тексте pdftotext.

    pdftotext сохраняет корректные пробелы между словами, в отличие от pdfplumber.

    Алгоритм:
    1. Найти строку с contract + суммой KZT (строка данных).
    2. Взять mid = текст перед contract на строке данных.
    3. Если mid начинается с org-prefix (АО/ТОО/etc.) — ведущих строк нет,
       creditor начинается прямо на строке данных.
       Иначе — сканируем НАЗАД до первой org-prefix строки (включаем её, стоп).
    4. Сканируем ВПЕРЁД: собираем строки до пустой / строки-данных /
       org-prefix (начало следующего кредитора — НЕ добавляем).
    """
    lines = block.split("\n")
    data_pat = re.compile(r'\d+\.\d{2}\s+KZT')
    # \b — граница слова, работает и когда ТОО/АО в конце строки
    org_pat = re.compile(r'^\s*(АО|ТОО|TOO|Акционерное)\b')

    # Найти строку данных
    data_idx = None
    for i, line in enumerate(lines):
        if contract in line and data_pat.search(line):
            data_idx = i
            break
    if data_idx is None:
        return ""

    data_line = lines[data_idx]
    contract_pos = data_line.find(contract)
    mid = data_line[:contract_pos].strip() if contract_pos > 0 else ""

    # Ведущие строки
    leading = []
    if not org_pat.match(mid):
        # mid — не начало кредитора, ищем начало выше
        for j in range(data_idx - 1, -1, -1):
            if not lines[j].strip():
                break
            if data_pat.search(lines[j]):
                break
            # Guard: строка сразу после предыдущей строки-данных — хвост того обязательства
            if j > 0 and data_pat.search(lines[j - 1]):
                break
            leading.insert(0, lines[j].strip())
            # Нашли начало имени кредитора (org-prefix) — стоп
            if org_pat.match(lines[j]):
                break

    # Хвостовые строки
    trailing = []
    for j in range(data_idx + 1, len(lines)):
        if not lines[j].strip():
            break
        if data_pat.search(lines[j]):
            break
        # Начало следующего кредитора — стоп, не включаем
        if org_pat.match(lines[j]):
            break
        trailing.append(lines[j].strip())

    parts = leading + ([mid] if mid else []) + trailing
    return " ".join(p for p in parts if p)


def _parse_short_obligations_plumber(pdf_bytes: bytes, text: str = "") -> list[Obligation]:
    """Извлечь обязательства через pdfplumber таблицы.

    pdfplumber правильно группирует строки по обязательствам,
    решая проблему многострочных имён кредиторов.
    """
    obligations = []

    # Извлечь блок обязательств из pdftotext для гибридного поиска кредиторов
    oblig_block = ""
    if text:
        block_m = re.search(
            r"платежа/валюта\s*\n(.*?)(?:ВАЖНАЯ ИНФОРМАЦИЯ|\Z)",
            text,
            re.DOTALL,
        )
        if block_m:
            oblig_block = block_m.group(1)
        else:
            wider_m = re.search(
                r"ОБЩАЯ ИНФОРМАЦИЯ ПО ОБЯЗАТЕЛЬСТВАМ.*?\n(.*?)(?:ВАЖНАЯ ИНФОРМАЦИЯ|\Z)",
                text,
                re.DOTALL,
            )
            if wider_m:
                oblig_block = wider_m.group(1)

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if "Кредитор" not in page_text:
                continue

            tables = page.extract_tables()
            if not tables:
                continue

            # Найти таблицу с обязательствами (содержит KZT данные, >3 строки)
            # Может быть table[0] или table[1] в зависимости от PDF
            obligations_table = None
            for tbl in tables:
                if len(tbl) < 3:
                    continue
                # Проверяем что таблица содержит данные KZT (не просто сводку)
                kzt_rows = sum(1 for r in tbl if r and r[0] and "KZT" in str(r[0]))
                if kzt_rows >= 2:
                    obligations_table = tbl
                    break

            if not obligations_table:
                continue

            for row in obligations_table:
                cell = str(row[0]) if row and row[0] else ""
                if not cell.strip():
                    continue

                # Объединяем строки в одну
                cell_text = cell.replace("\n", " ")

                # Пропускаем заголовок
                if "Кредитор" in cell_text and "Номер" in cell_text:
                    continue

                # Ищем данные: contract_number [..] amount.ddKZT days date payment
                # Между номером и суммой может быть ".." (артефакт PDF)
                m = re.search(
                    r"(\S+)\s+"                                    # Номер договора
                    r"(?:\.{1,3}\s+)?"                             # Опциональный ".." / "..." шум
                    r"(\d[\d,]*\.\d{2})KZT\s+"                   # Сумма задолженности (.NN обязательно)
                    r"(\d+)\s+"                                    # Дни просрочки
                    r"(\d{4}-\d{2}-\d{2}|Нетданных)\s+"          # Дата последнего платежа
                    r"(\d[\d,]*\.\d{2}KZT|Нетданных)",            # Сумма последнего платежа
                    cell_text,
                )

                if not m:
                    continue

                contract_number = m.group(1).strip()
                # Убираем ".." из конца номера договора
                contract_number = contract_number.rstrip(".")

                debt_amount = _parse_kzt_amount(m.group(2))
                overdue_days_str = m.group(3).strip()
                raw_date = m.group(4).replace("Нетданных", "")
                last_payment_date = _clean(raw_date) if raw_date else None
                raw_payment = m.group(5).replace("KZT", "").replace("Нетданных", "")
                last_payment_amount = _parse_kzt_amount(raw_payment) if raw_payment else None

                overdue_days = None
                try:
                    overdue_days = int(overdue_days_str)
                except ValueError:
                    pass

                # Кредитор: гибридный подход — ищем в pdftotext по номеру договора
                creditor_name = ""
                if oblig_block:
                    creditor_name = _find_creditor_in_text(oblig_block, contract_number)

                # Fallback: из pdfplumber ячейки с исправлением пробелов
                if not creditor_name:
                    before = cell_text[:m.start()].strip()
                    after = cell_text[m.end():].strip()
                    creditor_raw = f"{before} {after}".strip()
                    creditor_name = _fix_creditor_spacing(creditor_raw)

                if not creditor_name:
                    creditor_name = "Неизвестный кредитор"

                obligation = Obligation(
                    creditor=creditor_name,
                    contract_number=contract_number,
                    overdue_amount=debt_amount,
                    overdue_days=overdue_days,
                    last_payment_date=last_payment_date,
                    last_payment_amount=last_payment_amount,
                )
                obligations.append(obligation)

    return obligations


def _parse_short_obligations_text(text: str) -> list[Obligation]:
    """Fallback: извлечь обязательства из текста (pdftotext).

    Используется если pdfplumber не нашёл таблицу.
    """
    obligations = []

    block_match = re.search(
        r"платежа/валюта\s*\n(.*?)(?:ВАЖНАЯ ИНФОРМАЦИЯ)",
        text,
        re.DOTALL,
    )
    if not block_match:
        block_match = re.search(
            r"ОБЩАЯ ИНФОРМАЦИЯ ПО ОБЯЗАТЕЛЬСТВАМ В РАЗРЕЗЕ КРЕДИТОРОВ.*?"
            r"(?:платежа/валюта)\s*\n(.*?)(?:ВАЖНАЯ ИНФОРМАЦИЯ|\Z)",
            text,
            re.DOTALL,
        )
    if not block_match:
        return obligations

    block = block_match.group(1)

    data_pattern = re.compile(
        r"(\d[\d,]*\.\d{2})\s+KZT\s+"
        r"(\d+)\s+"
        r"(\d{4}-\d{2}-\d{2}|Нет данных)\s+"
        r"(\d[\d,]*\.\d{2}\s+KZT|Нет данных)"
    )

    matches = list(data_pattern.finditer(block))

    for i, match in enumerate(matches):
        debt_amount = _parse_kzt_amount(match.group(1))
        overdue_days_str = match.group(2).strip()
        last_payment_date = _clean(match.group(3).strip())
        last_payment_amount = _parse_kzt_amount(match.group(4))

        overdue_days = None
        try:
            overdue_days = int(overdue_days_str)
        except ValueError:
            pass

        line_start = block.rfind("\n", 0, match.start()) + 1
        text_before = block[line_start:match.start()].strip()

        tokens = text_before.split()
        contract_number = None
        creditor_line_tokens = []
        for j in range(len(tokens) - 1, -1, -1):
            token = tokens[j]
            if contract_number is None:
                if token in ("..", "...", "."):
                    continue
                contract_number = token
            else:
                creditor_line_tokens.insert(0, token)

        if not contract_number:
            contract_number = "Неизвестно"

        if i > 0:
            prev_end = matches[i - 1].end()
            prev_line_end = block.find("\n", prev_end)
            if prev_line_end == -1:
                prev_line_end = prev_end
            between = block[prev_line_end:line_start]
        else:
            between = block[:line_start]

        cred_lines = []
        for line in between.strip().split("\n"):
            cleaned = line.strip()
            if not cleaned:
                continue
            if "Страница" in cleaned and "из" in cleaned:
                continue
            cred_lines.append(cleaned)

        if creditor_line_tokens:
            cred_lines.append(" ".join(creditor_line_tokens))

        creditor_name = " ".join(cred_lines).strip()
        if not creditor_name:
            creditor_name = "Неизвестный кредитор"

        obligation = Obligation(
            creditor=creditor_name,
            contract_number=contract_number,
            overdue_amount=debt_amount,
            overdue_days=overdue_days,
            last_payment_date=last_payment_date,
            last_payment_amount=last_payment_amount,
        )
        obligations.append(obligation)

    return obligations


def _parse_short_obligations(text: str, pdf_bytes: bytes) -> list[Obligation]:
    """Извлечь обязательства из сводной таблицы кредиторов.

    Первый вариант: pdfplumber (правильная группировка строк).
    Fallback: regex по тексту pdftotext.
    """
    try:
        obligations = _parse_short_obligations_plumber(pdf_bytes, text)
        if obligations:
            return obligations
    except Exception:
        pass

    return _parse_short_obligations_text(text)


def parse_gkb_short_report(text: str, pdf_bytes: bytes) -> GkbReport:
    """Спарсить краткую форму отчёта ГКБ -> GkbReport."""

    # 1. Персональные данные
    personal = _parse_short_personal(text)

    # 2. Адреса (с фильтрацией двухколоночного layout)
    residential = _extract_address_short(text, "Постоянное место жительства")
    registration = _extract_address_short(text, "Место прописки")

    # 3. Документы удостоверения личности
    identity_documents = _parse_short_documents(text, pdf_bytes)

    # 4. Обязательства (сводная таблица по кредиторам)
    active_obligations = _parse_short_obligations(text, pdf_bytes)

    # 5. Общая сумма задолженности и кол-во обязательств
    total_debt = _extract_float(text, r"(?:Общая сумма задолженности/валюта:)\s*\n?\s*([\d\s,.]+)\s*KZT")
    active_count = _extract_int(text, r"Действующие обязательства:\s*(\d+)")

    # 6. Собрать отчёт
    report = GkbReport(
        # Метаданные
        report_number=personal.get("report_number"),
        report_date=personal.get("report_date"),
        report_time=personal.get("report_time"),
        report_type=personal.get("report_type"),
        # Личные данные
        client_name=personal.get("client_name", "Неизвестно"),
        last_name=personal.get("last_name"),
        first_name=personal.get("first_name"),
        middle_name=personal.get("middle_name"),
        iin=personal.get("iin"),
        birth_date=personal.get("birth_date"),
        citizenship=personal.get("citizenship"),
        gender=personal.get("gender"),
        # Контакты
        phone_mobile=personal.get("phone_mobile"),
        phone_work=personal.get("phone_work"),
        phone_home=personal.get("phone_home"),
        email=personal.get("email"),
        # Адреса
        residential_address=residential,
        registration_address=registration,
        # Обязательства
        active_obligations=active_obligations,
        completed_obligations=[],
        # Документы
        identity_documents=identity_documents,
    )

    return report
