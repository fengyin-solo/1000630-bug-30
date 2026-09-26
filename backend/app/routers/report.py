"""报告出具接口：维护检测报告，覆盖提交编制、确认签发、作废报告等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.report import STATUS_ORDER, ReportService

router = APIRouter(prefix="/api/report", tags=["报告出具"])

service = ReportService()

LIST_FIELDS = ["报告编号", "关联样品", "报告类型", "编制人员", "审核人员", "签发人员", "出具日期", "报告状态"]
STATUSES = list(STATUS_ORDER)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按报告编号检索（兼容旧入口）"),
    report_no: str | None = Query(default=None, description="按报告编号检索"),
    report_type: str | None = Query(default=None, description="按报告类型检索"),
    issuer: str | None = Query(default=None, description="按签发人员检索"),
    status: str | None = Query(default=None, description="待编制、已编制、待签发、已出具、已作废"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1),
) -> PageResult[dict]:
    """按报告编号、报告类型、签发人员与状态过滤报告列表。

    筛选在分页前统一完成，翻页不会混入未命中记录；清空某个条件时传空串等同不传。
    没有命中时返回空页与 total=0，由前端说明原因，不会退回全量数据。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    status_value = (status or "").strip()
    if status_value and status_value not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"报告状态「{status_value}」不支持，可选：{'、'.join(STATUSES)}",
        )
    items, total = service.list_entries(
        keyword=keyword,
        report_no=report_no,
        report_type=report_type,
        issuer=issuer,
        status=status_value or None,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出报告出具清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
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
