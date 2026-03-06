"""FastAPI микросервис для парсинга отчётов ГКБ."""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from app.parser import parse_gkb_report
from app.models import GkbReport

app = FastAPI(
    title="GKB Parser",
    description="Микросервис для парсинга персональных кредитных отчётов ГКБ (PDF → JSON)",
    version="1.0.0",
)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/parse", response_model=GkbReport)
async def parse_pdf(file: UploadFile = File(...)):
    """
    Загрузить PDF отчёта ГКБ → получить структурированный JSON.

    Поддерживает:
    - Полную форму (Персональный кредитный отчет)
    - Краткую форму (в рамках внесудебной процедуры банкротства)
    - PDF с ЭЦП (автоматически обрезается)
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате PDF")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Пустой файл")

    try:
        report = parse_gkb_report(content)
        return report
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка парсинга: {type(e).__name__}: {str(e)}",
        )


@app.post("/parse/summary")
async def parse_pdf_summary(file: UploadFile = File(...)):
    """
    Краткая выжимка: ФИО, общий долг, количество обязательств.
    Для быстрой проверки без полного парсинга.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате PDF")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Пустой файл")

    try:
        report = parse_gkb_report(content)

        total_debt = sum(
            o.overdue_amount or 0 for o in report.active_obligations
        )

        return {
            "client_name": report.client_name,
            "iin": report.iin,
            "active_count": len(report.active_obligations),
            "completed_count": len(report.completed_obligations),
            "total_active_debt": total_debt,
            "creditors": list(set(o.creditor for o in report.active_obligations)),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка парсинга: {type(e).__name__}: {str(e)}",
        )
