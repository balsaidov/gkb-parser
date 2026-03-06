"""Извлечение обязательств из отчёта ГКБ."""
import re
from typing import Optional

from app.models import (
    Obligation,
    Collateral,
    Cession,
    ParentContract,
    DebtCollection,
    RelatedSubject,
    OverdueYear,
    OverdueMonth,
)


def _clean(value: str) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if value.lower() in ("нет данных", "нет данных.", "-", ""):
        return None
    return value


def _extract(text: str, pattern: str, flags=0) -> Optional[str]:
    m = re.search(pattern, text, flags)
    if m:
        return _clean(m.group(1))
    return None


def _extract_col(text: str, pattern: str, flags=0) -> Optional[str]:
    """Извлечь значение, обрезая по границе колонки (2+ пробела)."""
    m = re.search(pattern, text, flags)
    if m:
        raw = m.group(1)
        raw = re.split(r"\s{2,}", raw)[0]
        return _clean(raw)
    return None


def _extract_float(text: str, pattern: str) -> Optional[float]:
    val = _extract(text, pattern)
    if val:
        val = val.replace(" ", "").replace(",", ".").replace("KZT", "").strip()
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _extract_int(text: str, pattern: str) -> Optional[int]:
    val = _extract(text, pattern)
    if val:
        try:
            return int(val.replace(" ", ""))
        except ValueError:
            return None
    return None


def _extract_rate(text: str, pattern: str) -> Optional[float]:
    val = _extract(text, pattern)
    if val:
        val = val.replace("%", "").replace(",", ".").strip()
        try:
            return float(val)
        except ValueError:
            return None
    return None


def split_obligation_blocks(text: str, section_header: str) -> list[str]:
    """
    Разбить секцию на блоки по 'Обязательство N'.
    section_header: 'ПОДРОБНАЯ ИНФОРМАЦИЯ ПО ДЕЙСТВУЮЩИМ ДОГОВОРАМ'
                 или 'ПОДРОБНАЯ ИНФОРМАЦИЯ О ЗАВЕРШЕННЫХ ДОГОВОРАХ'
    """
    # Найти начало секции
    start = text.find(section_header)
    if start == -1:
        return []

    # Найти конец секции (следующий крупный заголовок)
    end_markers = [
        "ПОДРОБНАЯ ИНФОРМАЦИЯ О ЗАВЕРШЕННЫХ ДОГОВОРАХ",
        "Текущие сведения о субъекте кредитной истории",
        "ВАЖНАЯ ИНФОРМАЦИЯ:",
        "Количество запросов по кредитной истории",
    ]

    section_text = text[start:]
    end_pos = len(section_text)
    for marker in end_markers:
        if marker == section_header:
            continue
        pos = section_text.find(marker)
        if pos > 0 and pos < end_pos:
            end_pos = pos

    section_text = section_text[:end_pos]

    # Разбить на блоки по "Обязательство N"
    blocks = re.split(r"(?=(?:^\s*|\n\s*)Обязательство\s+\d+)", section_text)
    # Первый элемент — заголовок секции, пропускаем
    blocks = [b for b in blocks if re.search(r"Обязательство\s+\d+", b)]

    return blocks


def parse_obligation(block: str) -> Obligation:
    """Парсинг одного блока обязательства."""

    # --- Общая информация ---
    subject_role = _extract_col(block, r"Роль субъекта:\s*(.+)")
    creditor = _extract_col(block, r"Кредитор:\s*(.+)") or "Неизвестно"
    bin_val = _extract(block, r"БИН:\s*(\d+)")
    credit_purpose = _extract_col(block, r"Цель кредита:\s*(.+)")
    financing_type = _extract_col(block, r"Вид финансирования:\s*(.+)")
    contract_status = _extract_col(block, r"Статус договора:\s*(.+)")
    condition_change = _extract_col(block, r"Признак изменения условий по договору:\s*(.+)")
    total_installments = _extract_int(block, r"Общее количество взносов:\s*(\d+)")

    # Объект кредитования (может быть многострочным)
    credit_object_match = re.search(
        r"Объект кредитования:\s*(.+?)(?=Вид финансирования|$)", block, re.DOTALL
    )
    credit_object = None
    if credit_object_match:
        credit_object = _clean(re.sub(r"\s+", " ", credit_object_match.group(1).strip()))

    # --- Договор ---
    contract_type = _extract_col(block, r"Тип контракта:\s*(.+)")
    contract_phase = _extract_col(block, r"Фаза контракта:\s*(.+)")
    contract_code = _extract_col(block, r"Код контракта:\s*(.+)")
    contract_number = _extract_col(block, r"Номер договора:\s*(.+)") or "Неизвестно"
    application_date = _extract(block, r"Дата заявки на кредит:\s*([\d.]+)")
    start_date = _extract(block, r"Дата начала срока действия контракта:\s*([\d.]+)")
    end_date = _extract(block, r"Дата окончания срока действия контракта:\s*([\d.]+)")
    actual_issue_date = _extract(block, r"Дата фактической выдачи:\s*([\d.]+)")
    payment_frequency = _extract_col(block, r"Периодичность платежей:\s*(.+)")
    nominal_rate = _extract_rate(block, r"Номинальная ставка вознаграждения:\s*([\d.,]+\s*%?)")
    effective_rate = _extract_rate(
        block, r"Годовая эффективная ставка вознаграждения:\s*([\d.,]+\s*%?)"
    )

    # --- Баланс ---
    total_amount = _extract_float(block, r"Общая сумма договора\s*/валюта:\s*([\d\s.,]+)\s*KZT")
    monthly_payment = _extract_float(
        block, r"Сумма ежемесячного платежа\s*/валюта:\s*([\d\s.,]+)\s*KZT"
    )
    overdue_amount = _extract_float(
        block, r"Сумма просроченных взносов\s*/валюта:\s*([\d\s.,]+)\s*KZT"
    )
    upcoming_payments = _extract_float(
        block, r"Сумма предстоящих платежей\s*/валюта:\s*([\d\s.,]+)\s*KZT"
    )
    overdue_days = _extract_int(block, r"Количество дней просрочки:\s*(\d+)")
    outstanding_installments = _extract_int(
        block, r"Кол-во непогашенных \(предстоящих\) платежей:\s*(\d+)"
    )
    penalty = _extract_float(block, r"Пеня\s*/валюта:\s*([\d\s.,]+)\s*KZT")
    fine = _extract_float(block, r"Штраф\s*/валюта:\s*([\d\s.,]+)\s*KZT")
    last_payment_date = _extract(
        block, r"Дата последнего произведенного платежа:\s*([\d.]+)"
    )
    last_payment_amount = _extract_float(
        block, r"Сумма последнего произведенного платежа/валюта:\s*([\d\s.,]+)\s*KZT"
    )

    # --- Обеспечения ---
    collaterals = []
    collateral_blocks = re.findall(
        r"Обеспечение\s*-\s*\d+(.+?)(?=Обеспечение\s*-\s*\d+|Сведения о цессионарии|Дополнительная информация)",
        block,
        re.DOTALL,
    )
    for cb in collateral_blocks:
        c = Collateral()
        c.type = _extract(cb, r"Вид обеспечения:\s*(.+)")
        c.value = _extract_float(cb, r"Стоимость обеспечения\s*/валюта:\s*([\d\s.,]+)\s*KZT")
        c.valuation_type = _extract(cb, r"Вид стоимости обеспечения:\s*(.+)")
        collaterals.append(c)

    # --- Дополнительная информация ---
    principal_grace = _extract(block, r"Льготный период по основному долгу:\s*(.+)")
    interest_grace = _extract(block, r"Льготный период по вознаграждению:\s*(.+)")
    prolongation_count = _extract_int(block, r"Количество пролонгаций:\s*(\d+)")
    prolongation_date = _extract(block, r"Дата пролонгации:\s*([\d.\-]+)")

    # --- Цессия ---
    cession = None
    assignee = _extract(
        block,
        r"Наименование лица, которому уступлено право \(требование\)\s*по договору:\s*(.+)",
    )
    if assignee:
        cession = Cession(
            assignee_name=assignee,
            assignee_bin=_extract(
                block,
                r"БИН лица, которому уступлено право \(требование\)\s*по договору:\s*(\d+)",
            ),
            assigned_amount=_extract_float(
                block,
                r"Сумма уступленного права \(требования\) по договору:\s*([\d\s.,]+)",
            ),
            assignment_date=_extract(
                block,
                r"Дата уступки права \(требования\) по договору\s*([\d.\-]+)",
            ),
        )

    # --- Родительский контракт ---
    parent_contracts = []
    pc_blocks = re.findall(
        r"Поставщик родительского контракта:\s*(.+?)(?=Поставщик родительского контракта:|Сведения о проведении|$)",
        block,
        re.DOTALL,
    )
    for pcb in pc_blocks:
        pc = ParentContract()
        pc.provider = _clean(pcb.split("\n")[0].strip()) if pcb else None
        pc.provider_bin = _extract(pcb, r"БИН поставщика родительского контракта:\s*(\d+)")
        pc.contract_number = _extract(pcb, r"Номер родительского контракта:\s*(.+)")
        pc.contract_date = _extract(
            pcb, r"Дата родительского контракта документа:\s*([\d.\-]+)"
        )
        if any([pc.provider, pc.provider_bin, pc.contract_number]):
            parent_contracts.append(pc)

    # --- Взыскание ---
    debt_collection = None
    basis = _extract(block, r"Основание для взыскания:\s*(.+)")
    if basis:
        debt_collection = DebtCollection(
            basis=basis,
            document_date=_extract(block, r"Дата документа о взыскании:\s*([\d.\-]+)"),
            cancellation_date=_extract(
                block, r"Дата отмены документа о взыскании:\s*([\d.\-]+)"
            ),
        )

    # --- Урегулирование ---
    debt_settlement_match = re.search(
        r"Сведения о проведении урегулирования задолженности:\s*(.+?)(?=Сведения о проведении взыскания)",
        block,
        re.DOTALL,
    )
    debt_settlement = None
    if debt_settlement_match:
        debt_settlement = _clean(debt_settlement_match.group(1).strip())

    # --- Помесячная история ---
    overdue_history = parse_overdue_history(block)

    # --- Общая инфо по просрочке ---
    max_overdue_days = _extract_int(
        block,
        r"Максимальное количество дней просрочки\s*с начала действия обязательства:\s*(\d[\d\s]*)",
    )
    max_overdue_amount = _extract_float(
        block,
        r"Максимальная сумма просрочки с начала\s*действия обязательства/валюта:\s*([\d\s.,]+)\s*KZT",
    )

    return Obligation(
        subject_role=subject_role,
        creditor=creditor,
        bin=bin_val,
        credit_purpose=credit_purpose,
        credit_object=credit_object,
        financing_type=financing_type,
        contract_status=contract_status,
        condition_change=condition_change,
        total_installments=total_installments,
        contract_type=contract_type,
        contract_phase=contract_phase,
        contract_code=contract_code,
        contract_number=contract_number,
        application_date=application_date,
        start_date=start_date,
        end_date=end_date,
        actual_issue_date=actual_issue_date,
        payment_frequency=payment_frequency,
        nominal_rate=nominal_rate,
        effective_rate=effective_rate,
        total_amount=total_amount,
        monthly_payment=monthly_payment,
        overdue_amount=overdue_amount,
        upcoming_payments=upcoming_payments,
        overdue_days=overdue_days,
        outstanding_installments=outstanding_installments,
        penalty=penalty,
        fine=fine,
        last_payment_date=last_payment_date,
        last_payment_amount=last_payment_amount,
        collaterals=collaterals,
        principal_grace_period=principal_grace,
        interest_grace_period=interest_grace,
        prolongation_count=prolongation_count,
        prolongation_date=prolongation_date,
        cession=cession,
        parent_contracts=parent_contracts,
        debt_settlement=debt_settlement,
        debt_collection=debt_collection,
        overdue_history=overdue_history,
        max_overdue_days=max_overdue_days,
        max_overdue_amount=max_overdue_amount,
    )


def parse_overdue_history(block: str) -> list[OverdueYear]:
    """Парсинг помесячных таблиц просрочек."""
    history = []

    # Найти все годовые блоки
    year_pattern = re.compile(
        r"(\d{4})\s+год\s*\n"
        r"Месяцы\s+01\s+02\s+03\s+04\s+05\s+06\s+07\s+08\s+09\s+10\s+11\s+12\s*\n"
        r"\s*Дни\s*\n"
        r"просрочки\s+(.*?)\n"
        r"\s*\n"
        r"\s*Сумма\s*\n"
        r"просрочки\s+(.*?)(?:\n|$)",
        re.DOTALL,
    )

    for m in year_pattern.finditer(block):
        year = int(m.group(1))
        days_line = m.group(2).strip()
        amounts_line = m.group(3).strip()

        # Парсим дни просрочки
        days_values = re.split(r"\s{2,}", days_line)
        # Парсим суммы (могут содержать KZT)
        amounts_raw = re.split(r"\s{2,}", amounts_line)

        months = []
        for i in range(min(12, len(days_values))):
            month_num = i + 1
            day_val = days_values[i].strip() if i < len(days_values) else "-"
            amt_val = amounts_raw[i].strip() if i < len(amounts_raw) else "-"

            overdue_days_val = None
            if day_val not in ("-", ""):
                try:
                    overdue_days_val = int(day_val)
                except ValueError:
                    pass

            overdue_amount_val = None
            if amt_val not in ("-", ""):
                cleaned = amt_val.replace("KZT", "").replace(" ", "").replace(",", ".").strip()
                try:
                    overdue_amount_val = float(cleaned)
                except ValueError:
                    pass

            months.append(
                OverdueMonth(
                    month=month_num,
                    overdue_days=overdue_days_val,
                    overdue_amount=overdue_amount_val,
                )
            )

        history.append(OverdueYear(year=year, months=months))

    return history
