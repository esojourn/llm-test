"""Page routes — server-rendered HTML via Jinja2."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..templates_conf import templates
from ..database import get_db
from ..models import TestReport

router = APIRouter()


@router.get("/")
async def index(request: Request):
    test_mode = os.environ.get("LLM_TEST_MODE") == "1"
    return templates.TemplateResponse(request, "index.html", context={"test_mode": test_mode})


@router.get("/methodology")
async def methodology(request: Request):
    return templates.TemplateResponse(request, "methodology.html")


@router.get("/report/{report_id}")
async def report(request: Request, report_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report_obj = result.scalar_one_or_none()
    if not report_obj:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "report.html", context={"report": report_obj})


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")
