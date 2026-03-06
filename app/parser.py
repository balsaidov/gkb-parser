"""Главный модуль парсинга отчёта ГКБ."""
import io
import subprocess
import tempfile
import os

from app.models import GkbReport
from app.extractors.personal import (
    extract_personal_info,
    extract_address,
    extract_bankruptcy,
    extract_gambling,
)
from app.extractors.obligations import split_obligation_blocks, parse_obligation
from app.extractors.tables import extract_tables_from_pdf
from app.extractors.short import parse_gkb_short_report


def strip_eds(pdf_bytes: bytes) -> bytes:
    """Обрезать ЭЦП (электронную цифровую подпись) в начале файла."""
    marker = b"%PDF"
    idx = pdf_bytes.find(marker)
    if idx > 0:
        return pdf_bytes[idx:]
    return pdf_bytes


def extract_text_pdftotext(pdf_bytes: bytes) -> str:
    """Извлечь текст из PDF через pdftotext -layout."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", tmp_path, "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    finally:
        os.unlink(tmp_path)


def extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    """Извлечь текст через pdfplumber (fallback)."""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def detect_report_type(text: str) -> str:
    """
    Определить тип отчёта по содержимому.

    Возвращает:
        'gkb_short' — краткая форма (в рамках внесудебной процедуры банкротства)
        'gkb_full'  — полная форма (персональный кредитный отчёт)
    """
    lower = text[:2000].lower()
    if "краткая форма" in lower:
        return "gkb_short"
    return "gkb_full"


def parse_gkb_report(raw_pdf_bytes: bytes) -> GkbReport:
    """
    Главная функция: PDF байты → GkbReport.

    Автоматически определяет тип отчёта (full/short) и применяет
    соответствующий парсер.

    Пайплайн:
    1. Обрезка ЭЦП
    2. Извлечение текста (pdftotext или pdfplumber)
    3. Определение типа отчёта
    4. Извлечение таблиц (pdfplumber)
    5. Парсинг секций (regex)
    6. Сборка в GkbReport
    """
    # 1. Обрезка ЭЦП
    pdf_bytes = strip_eds(raw_pdf_bytes)

    # 2. Извлечение текста
    try:
        text = extract_text_pdftotext(pdf_bytes)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # pdftotext не установлен — fallback на pdfplumber
        text = extract_text_pdfplumber(pdf_bytes)

    if not text.strip():
        raise ValueError("Не удалось извлечь текст из PDF")

    # 3. Определение типа отчёта
    report_type = detect_report_type(text)

    if report_type == "gkb_short":
        return parse_gkb_short_report(text, pdf_bytes)

    # 4. Извлечение таблиц через pdfplumber (только для full)
    table_data = extract_tables_from_pdf(pdf_bytes)

    # 4. Парсинг персональных данных
    personal = extract_personal_info(text)

    # 5. Парсинг адресов
    residential = extract_address(text, "Постоянное место жительства")
    registration = extract_address(text, "Место прописки")

    # 6. Банкротство и игорный бизнес
    bankruptcy = extract_bankruptcy(text)
    gambling = extract_gambling(text)

    # 7. Парсинг обязательств
    active_blocks = split_obligation_blocks(
        text, "ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ"
    )
    active_obligations = [parse_obligation(block) for block in active_blocks]

    completed_blocks = split_obligation_blocks(
        text, "ПОДРОБНАЯ ИНФОРМАЦИЯ О ЗАВЕРШЕННЫХ ДОГОВОРАХ"
    )
    completed_obligations = [parse_obligation(block) for block in completed_blocks]

    # 8. Сборка отчёта
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
        # Запрет на кредит
        credit_ban=personal.get("credit_ban"),
        credit_ban_start_date=personal.get("credit_ban_start_date"),
        credit_ban_end_date=personal.get("credit_ban_end_date"),
        # Адреса
        residential_address=residential,
        registration_address=registration,
        # Секции
        bankruptcy=bankruptcy,
        gambling_payments=gambling,
        credit_applications=table_data.get("credit_applications"),
        obligations_summary=table_data.get("obligations_summary"),
        # Обязательства
        active_obligations=active_obligations,
        completed_obligations=completed_obligations,
        # Документы
        identity_documents=table_data.get("identity_documents", []),
        # Запросы
        credit_queries=table_data.get("credit_queries"),
    )

    return report
