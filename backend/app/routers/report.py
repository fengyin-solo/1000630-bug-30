"""报告出具接口：维护检测报告，覆盖提交编制、确认签发、作废报告等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.report import STATUS_ORDER, ReportService

router = APIRouter(prefix="/api/report", tags=["报告出具"])

service = ReportService()

LIST_FIELDS = ["报告编号", "关联样品", "报告类型", "编制人员", "审核人员", "签发人员", "出具日期", "报告状态"]
STATUSES = STATUS_ORDER


def _read_filters(
    report_no: str | None,
    report_type: str | None,
    issuer: str | None,
) -> dict[str, str]:
    """把独立查询参数收敛成服务层的字段条件；空串视为未填，绝不让空白参与过滤。"""
    raw = {"报告编号": report_no, "报告类型": report_type, "签发人员": issuer}
    return {field: value for field, value in raw.items() if value is not None}


@router.get("", response_model=PageResult[dict])
def list_entries(
    response: Response,
    report_no: str | None = Query(default=None, alias="报告编号", description="按报告编号模糊检索"),
    report_type: str | None = Query(default=None, alias="报告类型", description="按报告类型模糊检索"),
    issuer: str | None = Query(default=None, alias="签发人员", description="按签发人员模糊检索"),
    keyword: str | None = Query(default=None, description="兼容旧入口：按报告编号检索"),
    status: str | None = Query(default=None, description="待编制、已编制、待签发、已出具、已作废"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1),
) -> PageResult[dict]:
    """按报告编号、报告类型、签发人员与状态过滤报告出具列表。

    所有条件为 AND 关系，先过滤后分页；没有命中时返回空页并在 message 说明原因。
    """
    # 列表是动态数据，禁止浏览器/代理复用旧查询结果，避免“清空条件仍沿用上次结果”。
    response.headers["Cache-Control"] = "no-store"
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status is not None and status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的报告状态「{status}」，可选：{'、'.join(STATUSES)}",
        )

    filters = _read_filters(report_no, report_type, issuer)
    if keyword and keyword.strip():
        filters.setdefault("报告编号", keyword)
    items, total, message = service.list_entries(
        filters=filters, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size, message=message)


@router.get("/export")
def export_entries(
    report_no: str | None = Query(default=None, alias="报告编号"),
    report_type: str | None = Query(default=None, alias="报告类型"),
    issuer: str | None = Query(default=None, alias="签发人员"),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    """导出报告出具清单：按当前筛选条件导出全量数据，作废报告不会混入在办状态结果。"""
    if status is not None and status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的报告状态「{status}」，可选：{'、'.join(STATUSES)}",
        )
    items, total, _ = service.list_entries(
        filters=_read_filters(report_no, report_type, issuer),
        status=status,
        page=1,
        size=10000,
    )
    return {"module": "report", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检测报告明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检测报告 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检测报告，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检测报告已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条检测报告执行提交编制、确认签发、作废报告；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
