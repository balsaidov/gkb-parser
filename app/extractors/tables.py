"""Извлечение таблиц из PDF через pdfplumber."""
import re
from typing import Optional

import pdfplumber

from app.models import (
    IdentityDocument,
    CreditQuery,
    CreditQueries,
    ObligationSummary,
    ObligationsSummary,
    CreditApplications,
    CreditApplication,
)


def _clean(value: str) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip()
    if value.lower() in ("нет данных", "нет данных.", "-", "", "none"):
        return None
    return value


def _parse_float(value: str) -> Optional[float]:
    val = _clean(value)
    if not val:
        return None
    val = val.replace(" ", "").replace(",", ".").replace("KZT", "").strip()
    try:
        return float(val)
    except ValueError:
        return None


def _parse_int(value: str) -> Optional[int]:
    val = _clean(value)
    if not val:
        return None
    try:
        return int(val.replace(" ", ""))
    except ValueError:
        return None


def extract_tables_from_pdf(pdf_bytes: bytes) -> dict:
    """
    Извлечь все таблицы из PDF с помощью pdfplumber.
    Возвращает словарь с распознанными таблицами по типам.
    """
    result = {
        "identity_documents": [],
        "credit_queries": None,
        "obligations_summary": None,
        "credit_applications": None,
    }

    with pdfplumber.open(_make_file_like(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            tables = page.extract_tables()

            if not tables:
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue

                header = _normalize_row(table[0])
                header_str = " ".join(str(h) for h in header if h).lower()

                # Таблица документов
                if "вид документа" in header_str and "номер" in header_str:
                    docs = _parse_identity_documents_table(table)
                    result["identity_documents"].extend(docs)

                # Таблица заявок на кредит
                elif "кредитор" in header_str and "заявки" in header_str:
                    apps = _parse_credit_applications_table(table)
                    if result["credit_applications"] is None:
                        result["credit_applications"] = CreditApplications()
                    result["credit_applications"].details.extend(apps)

                # Таблица запросов
                elif "дата/время запроса" in header_str:
                    queries = _parse_credit_queries_table(table)
                    if result["credit_queries"] is None:
                        result["credit_queries"] = CreditQueries()
                    result["credit_queries"].details.extend(queries)

            # Извлечь количество заявок
            app_count_match = re.search(
                r"Количество заявок на кредит за последние 30 календарных дней:\s*(\d+)",
                page_text,
            )
            if app_count_match:
                if result["credit_applications"] is None:
                    result["credit_applications"] = CreditApplications()
                result["credit_applications"].last_30_days_count = int(
                    app_count_match.group(1)
                )

            # Извлечь количество запросов
            if "Количество запросов по кредитной истории" in page_text:
                result["credit_queries"] = _parse_query_counts(
                    page_text, result["credit_queries"]
                )

    return result


def _make_file_like(pdf_bytes: bytes):
    """Создать file-like объект из байтов."""
    import io
    return io.BytesIO(pdf_bytes)


def _normalize_row(row: list) -> list:
    """Нормализовать строку таблицы."""
    return [str(cell).strip() if cell else "" for cell in row]


def _parse_identity_documents_table(table: list) -> list[IdentityDocument]:
    """Парсинг таблицы документов, удостоверяющих личность."""
    docs = []
    for row in table[1:]:  # Пропустить заголовок
        if len(row) < 5:
            continue
        row = _normalize_row(row)
        doc_type = _clean(row[0])
        number = _clean(row[1])

        if not doc_type and not number:
            continue

        doc = IdentityDocument(
            type=doc_type,
            number=number,
            issue_date=_clean(row[2]) if len(row) > 2 else None,
            expiry_date=_clean(row[3]) if len(row) > 3 else None,
            full_name=_clean(row[4]) if len(row) > 4 else None,
            bureau_received_date=_clean(row[5]) if len(row) > 5 else None,
        )
        docs.append(doc)

    return docs


def _parse_credit_applications_table(table: list) -> list[CreditApplication]:
    """Парсинг таблицы заявок на кредит."""
    apps = []
    for row in table[1:]:
        if len(row) < 5:
            continue
        row = _normalize_row(row)
        creditor = _clean(row[0])
        if not creditor:
            continue

        app = CreditApplication(
            creditor=creditor,
            bin=_clean(row[1]) if len(row) > 1 else None,
            application_number=_clean(row[2]) if len(row) > 2 else None,
            application_date=_clean(row[3]) if len(row) > 3 else None,
            amount=_parse_float(row[4]) if len(row) > 4 else None,
            purpose=_clean(row[5]) if len(row) > 5 else None,
            object=_clean(row[6]) if len(row) > 6 else None,
        )
        apps.append(app)

    return apps


def _parse_credit_queries_table(table: list) -> list[CreditQuery]:
    """Парсинг таблицы запросов по кредитной истории."""
    queries = []
    for row in table[1:]:
        if len(row) < 3:
            continue
        row = _normalize_row(row)
        date_time = _clean(row[0])
        if not date_time:
            continue

        q = CreditQuery(
            date_time=date_time,
            report_type=_clean(row[1]) if len(row) > 1 else None,
            recipient_name=_clean(row[2]) if len(row) > 2 else None,
            recipient_bin=_clean(row[3]) if len(row) > 3 else None,
        )
        queries.append(q)

    return queries


def _parse_query_counts(text: str, existing: Optional[CreditQueries]) -> CreditQueries:
    """Извлечь количество запросов за разные периоды."""
    cq = existing or CreditQueries()

    m7 = re.search(r"За последние 7 дней:\s*(\d+)", text)
    m30 = re.search(r"За последние 30 дней:\s*(\d+)", text)
    m90 = re.search(r"За последние 90 дней:\s*(\d+)", text)
    m365 = re.search(r"За последний год:\s*(\d+)", text)

    if m7:
        cq.last_7_days = int(m7.group(1))
    if m30:
        cq.last_30_days = int(m30.group(1))
    if m90:
        cq.last_90_days = int(m90.group(1))
    if m365:
        cq.last_year = int(m365.group(1))

    return cq
