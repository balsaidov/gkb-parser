"""gRPC servicer: реализует методы из gkb_parser.proto."""
import json
from typing import Optional

from app.parser import parse_gkb_report
from app.models import (
    GkbReport, Obligation, Address, Bankruptcy,
    GamblingPayments, Collateral, Cession, DebtCollection,
    RelatedSubject, ParentContract,
)
from app.proto import gkb_parser_pb2, gkb_parser_pb2_grpc

import grpc


# ─────────────────────────────────────────
# Вспомогательные конвертеры
# ─────────────────────────────────────────

def _set_opt_str(proto_msg, field: str, value: Optional[str]):
    if value is not None:
        setattr(proto_msg, field, value)


def _set_opt_float(proto_msg, field: str, value: Optional[float]):
    if value is not None:
        setattr(proto_msg, field, float(value))


def _set_opt_int(proto_msg, field: str, value: Optional[int]):
    if value is not None:
        setattr(proto_msg, field, int(value))


def _set_opt_bool(proto_msg, field: str, value: Optional[bool]):
    if value is not None:
        setattr(proto_msg, field, bool(value))


def _convert_address(addr: Optional[Address]) -> Optional[gkb_parser_pb2.Address]:
    if addr is None:
        return None
    pb = gkb_parser_pb2.Address()
    _set_opt_str(pb, "country", addr.country)
    _set_opt_str(pb, "region", addr.region)
    _set_opt_str(pb, "district", addr.district)
    _set_opt_str(pb, "city", addr.city)
    _set_opt_str(pb, "street", addr.street)
    _set_opt_str(pb, "house_apartment", addr.house_apartment)
    _set_opt_str(pb, "postal_code", addr.postal_code)
    return pb


def _convert_collateral(c: Collateral) -> gkb_parser_pb2.Collateral:
    pb = gkb_parser_pb2.Collateral()
    _set_opt_str(pb, "type", c.type)
    _set_opt_float(pb, "value", c.value)
    _set_opt_str(pb, "valuation_type", c.valuation_type)
    return pb


def _convert_cession(c: Optional[Cession]) -> Optional[gkb_parser_pb2.Cession]:
    if c is None:
        return None
    pb = gkb_parser_pb2.Cession()
    _set_opt_str(pb, "assignee_name", c.assignee_name)
    _set_opt_str(pb, "assignee_bin", c.assignee_bin)
    _set_opt_float(pb, "assigned_amount", c.assigned_amount)
    _set_opt_str(pb, "assignment_date", c.assignment_date)
    return pb


def _convert_debt_collection(dc: Optional[DebtCollection]) -> Optional[gkb_parser_pb2.DebtCollection]:
    if dc is None:
        return None
    pb = gkb_parser_pb2.DebtCollection()
    _set_opt_str(pb, "basis", dc.basis)
    _set_opt_str(pb, "document_date", dc.document_date)
    _set_opt_str(pb, "cancellation_date", dc.cancellation_date)
    return pb


def _convert_related_subject(rs: RelatedSubject) -> gkb_parser_pb2.RelatedSubject:
    pb = gkb_parser_pb2.RelatedSubject()
    _set_opt_str(pb, "role", rs.role)
    _set_opt_str(pb, "name", rs.name)
    _set_opt_str(pb, "iin_bin", rs.iin_bin)
    _set_opt_str(pb, "document_type", rs.document_type)
    _set_opt_str(pb, "document_number", rs.document_number)
    return pb


def _convert_parent_contract(pc: ParentContract) -> gkb_parser_pb2.ParentContract:
    pb = gkb_parser_pb2.ParentContract()
    _set_opt_str(pb, "provider", pc.provider)
    _set_opt_str(pb, "provider_bin", pc.provider_bin)
    _set_opt_str(pb, "contract_number", pc.contract_number)
    _set_opt_str(pb, "contract_date", pc.contract_date)
    return pb


def _convert_overdue_history(history: list) -> list:
    result = []
    for year_data in (history or []):
        pb_year = gkb_parser_pb2.OverdueYear()
        pb_year.year = year_data.year
        for m in (year_data.months or []):
            pb_month = gkb_parser_pb2.OverdueMonth()
            pb_month.month = m.month
            if m.overdue_days is not None:
                pb_month.overdue_days = m.overdue_days
            if m.overdue_amount is not None:
                pb_month.overdue_amount = float(m.overdue_amount)
            pb_year.months.append(pb_month)
        result.append(pb_year)
    return result


def _convert_obligation(ob: Obligation) -> gkb_parser_pb2.Obligation:
    pb = gkb_parser_pb2.Obligation()
    _set_opt_str(pb, "subject_role", ob.subject_role)
    pb.creditor = ob.creditor
    _set_opt_str(pb, "bin", ob.bin)
    _set_opt_str(pb, "credit_purpose", ob.credit_purpose)
    _set_opt_str(pb, "credit_object", ob.credit_object)
    _set_opt_str(pb, "financing_type", ob.financing_type)
    _set_opt_str(pb, "contract_status", ob.contract_status)
    _set_opt_str(pb, "condition_change", ob.condition_change)
    _set_opt_int(pb, "total_installments", ob.total_installments)
    _set_opt_str(pb, "contract_type", ob.contract_type)
    _set_opt_str(pb, "contract_phase", ob.contract_phase)
    _set_opt_str(pb, "contract_code", ob.contract_code)
    pb.contract_number = ob.contract_number
    _set_opt_str(pb, "application_date", ob.application_date)
    _set_opt_str(pb, "start_date", ob.start_date)
    _set_opt_str(pb, "end_date", ob.end_date)
    _set_opt_str(pb, "actual_issue_date", ob.actual_issue_date)
    _set_opt_str(pb, "payment_frequency", ob.payment_frequency)
    _set_opt_float(pb, "nominal_rate", ob.nominal_rate)
    _set_opt_float(pb, "effective_rate", ob.effective_rate)
    _set_opt_float(pb, "total_amount", ob.total_amount)
    _set_opt_float(pb, "monthly_payment", ob.monthly_payment)
    _set_opt_float(pb, "overdue_amount", ob.overdue_amount)
    _set_opt_float(pb, "upcoming_payments", ob.upcoming_payments)
    _set_opt_int(pb, "overdue_days", ob.overdue_days)
    _set_opt_int(pb, "outstanding_installments", ob.outstanding_installments)
    _set_opt_float(pb, "penalty", ob.penalty)
    _set_opt_float(pb, "fine", ob.fine)
    _set_opt_str(pb, "last_payment_date", ob.last_payment_date)
    _set_opt_float(pb, "last_payment_amount", ob.last_payment_amount)
    _set_opt_str(pb, "principal_grace_period", ob.principal_grace_period)
    _set_opt_str(pb, "interest_grace_period", ob.interest_grace_period)
    _set_opt_int(pb, "prolongation_count", ob.prolongation_count)
    _set_opt_str(pb, "prolongation_date", ob.prolongation_date)
    _set_opt_str(pb, "debt_settlement", ob.debt_settlement)
    _set_opt_int(pb, "max_overdue_days", ob.max_overdue_days)
    _set_opt_float(pb, "max_overdue_amount", ob.max_overdue_amount)

    for c in (ob.collaterals or []):
        pb.collaterals.append(_convert_collateral(c))

    if ob.cession:
        pb.cession.CopyFrom(_convert_cession(ob.cession))

    for pc in (ob.parent_contracts or []):
        pb.parent_contracts.append(_convert_parent_contract(pc))

    if ob.debt_collection:
        pb.debt_collection.CopyFrom(_convert_debt_collection(ob.debt_collection))

    for rs in (ob.related_subjects or []):
        pb.related_subjects.append(_convert_related_subject(rs))

    for oy in _convert_overdue_history(ob.overdue_history or []):
        pb.overdue_history.append(oy)

    return pb


def _convert_report(report: GkbReport) -> gkb_parser_pb2.GkbReport:
    pb = gkb_parser_pb2.GkbReport()

    if report.report_number is not None:
        pb.report_number = report.report_number
    _set_opt_str(pb, "report_date", report.report_date)
    _set_opt_str(pb, "report_time", report.report_time)
    _set_opt_str(pb, "report_type", report.report_type)
    pb.client_name = report.client_name
    _set_opt_str(pb, "last_name", report.last_name)
    _set_opt_str(pb, "first_name", report.first_name)
    _set_opt_str(pb, "middle_name", report.middle_name)
    _set_opt_str(pb, "iin", report.iin)
    _set_opt_str(pb, "birth_date", report.birth_date)
    _set_opt_str(pb, "citizenship", report.citizenship)
    _set_opt_str(pb, "gender", report.gender)
    _set_opt_str(pb, "phone_mobile", report.phone_mobile)
    _set_opt_str(pb, "phone_work", report.phone_work)
    _set_opt_str(pb, "phone_home", report.phone_home)
    _set_opt_str(pb, "email", report.email)
    _set_opt_bool(pb, "credit_ban", report.credit_ban)
    _set_opt_str(pb, "credit_ban_start_date", report.credit_ban_start_date)
    _set_opt_str(pb, "credit_ban_end_date", report.credit_ban_end_date)

    if report.residential_address:
        pb.residential_address.CopyFrom(_convert_address(report.residential_address))
    if report.registration_address:
        pb.registration_address.CopyFrom(_convert_address(report.registration_address))

    if report.bankruptcy:
        pb.bankruptcy.recognition_date = report.bankruptcy.recognition_date or ""
        pb.bankruptcy.completion_date = report.bankruptcy.completion_date or ""
        pb.bankruptcy.data_date = report.bankruptcy.data_date or ""

    if report.gambling_payments:
        if report.gambling_payments.total_count is not None:
            pb.gambling_payments.total_count = report.gambling_payments.total_count
        if report.gambling_payments.total_amount is not None:
            pb.gambling_payments.total_amount = float(report.gambling_payments.total_amount)

    for ob in (report.active_obligations or []):
        pb.active_obligations.append(_convert_obligation(ob))

    for ob in (report.completed_obligations or []):
        pb.completed_obligations.append(_convert_obligation(ob))

    for doc in (report.identity_documents or []):
        pb_doc = gkb_parser_pb2.IdentityDocument()
        _set_opt_str(pb_doc, "type", doc.type)
        _set_opt_str(pb_doc, "number", doc.number)
        _set_opt_str(pb_doc, "issue_date", doc.issue_date)
        _set_opt_str(pb_doc, "expiry_date", doc.expiry_date)
        _set_opt_str(pb_doc, "full_name", doc.full_name)
        _set_opt_str(pb_doc, "bureau_received_date", doc.bureau_received_date)
        pb.identity_documents.append(pb_doc)

    if report.military_service:
        _set_opt_str(pb.military_service, "status", report.military_service.status)
        _set_opt_str(pb.military_service, "start_date", report.military_service.start_date)

    if report.credit_queries:
        cq = report.credit_queries
        if cq.last_7_days is not None:
            pb.credit_queries.last_7_days = cq.last_7_days
        if cq.last_30_days is not None:
            pb.credit_queries.last_30_days = cq.last_30_days
        if cq.last_90_days is not None:
            pb.credit_queries.last_90_days = cq.last_90_days
        if cq.last_year is not None:
            pb.credit_queries.last_year = cq.last_year
        for q in (cq.details or []):
            pb_q = gkb_parser_pb2.CreditQuery()
            _set_opt_str(pb_q, "date_time", q.date_time)
            _set_opt_str(pb_q, "report_type", q.report_type)
            _set_opt_str(pb_q, "recipient_name", q.recipient_name)
            _set_opt_str(pb_q, "recipient_bin", q.recipient_bin)
            pb.credit_queries.details.append(pb_q)

    return pb


# ─────────────────────────────────────────
# gRPC Servicer
# ─────────────────────────────────────────

class GkbParserServicer(gkb_parser_pb2_grpc.GkbParserServicer):

    def Health(self, request, context):
        return gkb_parser_pb2.HealthResponse(status="ok")

    def Parse(self, request, context):
        try:
            report = parse_gkb_report(request.pdf_data)
            pb_report = _convert_report(report)
            return gkb_parser_pb2.ParseResponse(report=pb_report)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Ошибка парсинга: {type(e).__name__}: {e}")
            return gkb_parser_pb2.ParseResponse()

    def ParseSummary(self, request, context):
        try:
            report = parse_gkb_report(request.pdf_data)
            total_debt = sum(
                o.overdue_amount or 0.0 for o in report.active_obligations
            )
            summary = {
                "client_name": report.client_name,
                "iin": report.iin,
                "active_count": len(report.active_obligations),
                "completed_count": len(report.completed_obligations),
                "total_active_debt": total_debt,
                "creditors": list({o.creditor for o in report.active_obligations}),
            }
            return gkb_parser_pb2.ParseSummaryResponse(
                json_summary=json.dumps(summary, ensure_ascii=False)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Ошибка: {type(e).__name__}: {e}")
            return gkb_parser_pb2.ParseSummaryResponse()
