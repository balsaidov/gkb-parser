from pydantic import BaseModel
from typing import Optional


class Address(BaseModel):
    country: Optional[str] = None
    region: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    street: Optional[str] = None
    house_apartment: Optional[str] = None
    postal_code: Optional[str] = None


class CreditApplication(BaseModel):
    creditor: Optional[str] = None
    bin: Optional[str] = None
    application_number: Optional[str] = None
    application_date: Optional[str] = None
    amount: Optional[float] = None
    purpose: Optional[str] = None
    object: Optional[str] = None


class ObligationSummary(BaseModel):
    count: Optional[int] = None
    subject_role: Optional[str] = None
    total_contract_amount: Optional[float] = None
    total_overdue_amount: Optional[float] = None
    total_remaining_debt: Optional[float] = None
    financing_types: Optional[str] = None
    contract_statuses: Optional[str] = None


class Collateral(BaseModel):
    type: Optional[str] = None
    value: Optional[float] = None
    valuation_type: Optional[str] = None


class ParentContract(BaseModel):
    provider: Optional[str] = None
    provider_bin: Optional[str] = None
    contract_number: Optional[str] = None
    contract_date: Optional[str] = None


class RelatedSubject(BaseModel):
    role: Optional[str] = None
    name: Optional[str] = None
    iin_bin: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None


class OverdueMonth(BaseModel):
    month: int
    overdue_days: Optional[int] = None
    overdue_amount: Optional[float] = None


class OverdueYear(BaseModel):
    year: int
    months: list[OverdueMonth] = []


class Cession(BaseModel):
    assignee_name: Optional[str] = None
    assignee_bin: Optional[str] = None
    assigned_amount: Optional[float] = None
    assignment_date: Optional[str] = None


class DebtCollection(BaseModel):
    basis: Optional[str] = None
    document_date: Optional[str] = None
    cancellation_date: Optional[str] = None


class Obligation(BaseModel):
    """Одно обязательство (действующее или завершённое)"""
    # Общая информация
    subject_role: Optional[str] = None
    creditor: str
    bin: Optional[str] = None
    credit_purpose: Optional[str] = None
    credit_object: Optional[str] = None
    financing_type: Optional[str] = None
    contract_status: Optional[str] = None
    condition_change: Optional[str] = None
    total_installments: Optional[int] = None

    # Договор
    contract_type: Optional[str] = None
    contract_phase: Optional[str] = None
    contract_code: Optional[str] = None
    contract_number: str
    application_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    actual_issue_date: Optional[str] = None
    payment_frequency: Optional[str] = None
    nominal_rate: Optional[float] = None
    effective_rate: Optional[float] = None

    # Баланс
    total_amount: Optional[float] = None
    monthly_payment: Optional[float] = None
    overdue_amount: Optional[float] = None
    upcoming_payments: Optional[float] = None
    overdue_days: Optional[int] = None
    outstanding_installments: Optional[int] = None
    penalty: Optional[float] = None
    fine: Optional[float] = None
    last_payment_date: Optional[str] = None
    last_payment_amount: Optional[float] = None

    # Обеспечения
    collaterals: list[Collateral] = []

    # Дополнительно
    principal_grace_period: Optional[str] = None
    interest_grace_period: Optional[str] = None
    prolongation_count: Optional[int] = None
    prolongation_date: Optional[str] = None

    # Цессия
    cession: Optional[Cession] = None

    # Родительский контракт
    parent_contracts: list[ParentContract] = []

    # Урегулирование / взыскание
    debt_settlement: Optional[str] = None
    debt_collection: Optional[DebtCollection] = None

    # Связанные субъекты
    related_subjects: list[RelatedSubject] = []

    # Помесячная история просрочек
    overdue_history: list[OverdueYear] = []

    # Общая инфо по просрочке
    max_overdue_days: Optional[int] = None
    max_overdue_amount: Optional[float] = None


class Bankruptcy(BaseModel):
    recognition_date: Optional[str] = None
    completion_date: Optional[str] = None
    data_date: Optional[str] = None


class GamblingPayments(BaseModel):
    total_count: Optional[int] = None
    total_amount: Optional[float] = None


class CreditApplications(BaseModel):
    last_30_days_count: Optional[int] = None
    details: list[CreditApplication] = []


class ObligationsSummary(BaseModel):
    active: Optional[ObligationSummary] = None
    completed: Optional[ObligationSummary] = None


class IdentityDocument(BaseModel):
    type: Optional[str] = None
    number: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    full_name: Optional[str] = None
    bureau_received_date: Optional[str] = None


class CreditQuery(BaseModel):
    date_time: Optional[str] = None
    report_type: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_bin: Optional[str] = None


class CreditQueries(BaseModel):
    last_7_days: Optional[int] = None
    last_30_days: Optional[int] = None
    last_90_days: Optional[int] = None
    last_year: Optional[int] = None
    details: list[CreditQuery] = []


class MilitaryService(BaseModel):
    status: Optional[str] = None
    start_date: Optional[str] = None


class GkbReport(BaseModel):
    """Полный персональный кредитный отчёт ГКБ"""
    # Метаданные
    report_number: Optional[int] = None
    report_date: Optional[str] = None
    report_time: Optional[str] = None
    report_type: Optional[str] = None

    # Личные данные
    client_name: str
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    iin: Optional[str] = None
    birth_date: Optional[str] = None
    citizenship: Optional[str] = None
    gender: Optional[str] = None

    # Контакты
    phone_mobile: Optional[str] = None
    phone_work: Optional[str] = None
    phone_home: Optional[str] = None
    email: Optional[str] = None

    # Запрет на кредит
    credit_ban: Optional[bool] = None
    credit_ban_start_date: Optional[str] = None
    credit_ban_end_date: Optional[str] = None

    # Адреса
    residential_address: Optional[Address] = None
    registration_address: Optional[Address] = None

    # Секции
    bankruptcy: Optional[Bankruptcy] = None
    gambling_payments: Optional[GamblingPayments] = None
    credit_applications: Optional[CreditApplications] = None
    obligations_summary: Optional[ObligationsSummary] = None

    # Обязательства
    active_obligations: list[Obligation] = []
    completed_obligations: list[Obligation] = []

    # Документы
    identity_documents: list[IdentityDocument] = []

    # Прочее
    military_service: Optional[MilitaryService] = None
    credit_queries: Optional[CreditQueries] = None
