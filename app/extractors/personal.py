"""Извлечение персональных данных из первой страницы отчёта."""
import re
from typing import Optional

from app.models import Address, Bankruptcy, GamblingPayments


def _clean(value: str) -> Optional[str]:
    """Очистить значение. 'Нет данных' / пустое → None."""
    if not value:
        return None
    value = value.strip()
    if value.lower() in ("нет данных", "нет данных.", "-", ""):
        return None
    return value


def _extract(text: str, pattern: str) -> Optional[str]:
    """Извлечь значение по regex паттерну."""
    m = re.search(pattern, text)
    if m:
        return _clean(m.group(1))
    return None


def _extract_col(text: str, pattern: str) -> Optional[str]:
    """
    Извлечь значение из двухколоночного layout.
    Обрезает по 2+ пробелам (граница между колонками).
    """
    m = re.search(pattern, text)
    if m:
        raw = m.group(1)
        # Обрезать по границе колонки (2+ пробела)
        raw = re.split(r"\s{2,}", raw)[0]
        return _clean(raw)
    return None


def _extract_float(text: str, pattern: str) -> Optional[float]:
    """Извлечь число."""
    val = _extract_col(text, pattern)
    if val:
        val = val.replace(" ", "").replace(",", ".").replace("KZT", "").strip()
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _extract_int(text: str, pattern: str) -> Optional[int]:
    """Извлечь целое число."""
    val = _extract_col(text, pattern)
    if val:
        try:
            return int(val.replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_personal_info(text: str) -> dict:
    """Извлечь персональные данные из текста первой страницы."""
    data = {}

    # Все поля из двухколоночного layout — используем _extract_col
    # [ \t]* вместо \s* чтобы не прыгать через \n
    data["last_name"] = _extract_col(text, r"Фамилия:[ \t]*([^\n]+)")
    data["first_name"] = _extract_col(text, r"Имя:[ \t]*([^\n]+)")
    data["middle_name"] = _extract_col(text, r"Отчество:[ \t]*([^\n]+)")
    data["iin"] = _extract(text, r"ИИН:\s*(\d+)")
    data["birth_date"] = _extract(text, r"Дата рождения:\s*([\d.]+)")
    data["citizenship"] = _extract_col(text, r"Гражданство:\s*(.+)")
    data["gender"] = _extract_col(text, r"Пол:\s*(.+)")

    # ФИО
    parts = [p for p in [data["last_name"], data["first_name"], data["middle_name"]] if p]
    data["client_name"] = " ".join(parts) if parts else "Неизвестно"

    # Контакты — тоже двухколоночный layout
    data["phone_mobile"] = _extract_col(text, r"Моб\.\s*тел\.:\s*(.+)")
    data["phone_work"] = _extract_col(text, r"Раб\.?\s*тел\.:\s*(.+)")
    data["phone_home"] = _extract_col(text, r"Дом\.?\s*тел\.:\s*(.+)")
    data["email"] = _extract_col(text, r"E-mail:\s*(.+)")

    # Запрет на кредит
    ban_val = _extract(text, r"Запрет на выдачу кредита:\s*(Да|Нет)")
    data["credit_ban"] = ban_val == "Да" if ban_val else None
    data["credit_ban_start_date"] = _extract(
        text, r"Дата установки запрета на выдачу\s*\n?\s*кредита:\s*([\d\-:.]+)"
    )
    data["credit_ban_end_date"] = _extract(
        text, r"Дата окончания запрета на выдачу\s*\n?\s*кредита:\s*([\d\-:.]+)"
    )

    # Метаданные
    data["report_date"] = _extract(text, r"Дата выдачи:\s*([\d.]+)")
    data["report_time"] = _extract(text, r"Время выдачи:\s*([\d:]+)")
    data["report_number"] = _extract_int(text, r"Номер кредитного отчета:\s*(\d+)")
    data["report_type"] = _extract_col(
        text, r"Вид кредитного отчета:\s*(.+)"
    )

    return {k: v for k, v in data.items() if v is not None}


def extract_address(text: str, address_type: str) -> Optional[Address]:
    """
    Извлечь адрес по типу: 'Постоянное место жительства' или 'Место прописки'.
    """
    # Найти блок адреса
    pattern = rf"{address_type}\s*(.*?)(?:Место прописки|Примечание)"
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
    street_match = re.search(r"Улица:\s*(.+?)(?=Дом,\s*кв:)", block, re.DOTALL)
    if street_match:
        street = street_match.group(1).strip()
        # Убрать лишние пробелы и переносы, но сохранить структуру
        street = re.sub(r"\n\s*", " ", street)
        street = re.sub(r"\s{2,}", " ", street)
        addr.street = _clean(street)

    return addr


def extract_bankruptcy(text: str) -> Optional[Bankruptcy]:
    """Извлечь сведения о банкротстве."""
    if "Сведения о банкротстве" not in text:
        return None

    block_match = re.search(
        r"Сведения о банкротстве(.+?)(?:Сведения о платежах|ОБЩАЯ ИНФОРМАЦИЯ)",
        text,
        re.DOTALL,
    )
    if not block_match:
        return None

    block = block_match.group(1)

    # В двухколоночном layout даты на отдельных строках под заголовками
    # "Дата признания банкротом:" и "Дата завершения банкротства:"
    # Значения идут строкой ниже
    recognition = None
    completion = None
    data_date = None

    # Паттерн: заголовок на одной строке, значение на следующей
    rec_match = re.search(
        r"Дата признания банкротом:\s*\n\s*(.+?)(?:\s{2,}|\n)", block
    )
    if rec_match:
        recognition = _clean(rec_match.group(1).strip())

    comp_match = re.search(
        r"Дата завершения банкротства:\s*\n\s*(.+?)(?:\s{2,}|\n)", block
    )
    if comp_match:
        completion = _clean(comp_match.group(1).strip())

    data_match = re.search(
        r"Дата актуальности сведений:\s*(.+?)(?:\s{2,}|\n)", block
    )
    if data_match:
        data_date = _clean(data_match.group(1).strip())

    if not any([recognition, completion, data_date]):
        return None

    return Bankruptcy(
        recognition_date=recognition,
        completion_date=completion,
        data_date=data_date,
    )


def extract_gambling(text: str) -> Optional[GamblingPayments]:
    """Извлечь сведения о платежах в игорный бизнес."""
    if "игорного бизнеса" not in text:
        return None

    block_match = re.search(
        r"Сведения о платежах субъекта в пользу организатора игорного бизнеса(.+?)(?:Сведения о поданных|ОБЩАЯ ИНФОРМАЦИЯ)",
        text,
        re.DOTALL,
    )
    if not block_match:
        return None

    block = block_match.group(1)
    g = GamblingPayments()

    # Значения могут быть на строке ниже заголовка
    count_match = re.search(
        r"Общее количество платежей:\s*\n?\s*(\d+)", block
    )
    if count_match:
        g.total_count = int(count_match.group(1))

    amount_match = re.search(
        r"Общая сумма платежей,?\s*KZT:\s*\n?\s*([\d\s,.]+)", block
    )
    if amount_match:
        val = amount_match.group(1).replace(" ", "").replace(",", ".")
        try:
            g.total_amount = float(val)
        except ValueError:
            pass

    return g
