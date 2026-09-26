"""报告出具业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "report"
REQUIRED_FIELDS = ["报告编号", "关联样品", "报告类型"]
STATUS_ORDER = ["待编制", "已编制", "待签发", "已出具", "已作废"]
VOID_STATUS = "已作废"
# 仍需人工处理的状态：待编制、待审核签发都算待处理；已出具/已作废不算。
PENDING_STATUSES = ["待编制", "已编制", "待签发"]
# 每个动作只允许在指定状态下执行，作废后的报告不能再走任何流转（包括确认签发）。
ACTION_RULES = {
    "提交编制": {"target": "已编制", "allowed_from": ["待编制"]},
    "确认签发": {"target": "已出具", "allowed_from": ["待签发"]},
    "作废报告": {"target": "已作废", "allowed_from": ["待编制", "已编制", "待签发", "已出具"]},
}
NEGATIVE_ACTIONS = ["作废报告"]


def _normalized(value: str | None) -> str:
    """把空白筛选值归一为空串：清空条件后不能再残留上一次的过滤效果。"""
    return str(value or "").strip()


class ReportService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        report_no: str | None = None,
        report_type: str | None = None,
        issuer: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """所有筛选都在分页之前完成，保证翻页拿到的始终是同一批命中结果。"""
        rows = store.rows(MODULE)
        no_value = _normalized(report_no) or _normalized(keyword)
        type_value = _normalized(report_type)
        issuer_value = _normalized(issuer)
        status_value = _normalized(status)

        if no_value:
            rows = [row for row in rows if no_value in str(row.get("报告编号", ""))]
        if type_value:
            rows = [row for row in rows if type_value in str(row.get("报告类型", ""))]
        if issuer_value:
            rows = [row for row in rows if issuer_value in str(row.get("签发人员", ""))]
        if status_value:
            rows = [row for row in rows if row.get("status") == status_value]

        total = len(rows)
        page = max(page, 1)
        size = max(size, 1)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检测报告 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于报告出具可执行范围"
        rule = ACTION_RULES[action]
        target = rule["target"]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        current = str(entry.get("status") or "")
        if current == VOID_STATUS:
            return None, f"检测报告已作废，不能再执行{action}，请确认是否误用了旧的签发入口"
        if current not in rule["allowed_from"]:
            if action == "确认签发":
                return None, f"检测报告当前状态为「{current}」，仅「待签发」状态的报告可以确认签发"
            if action == "提交编制":
                return None, f"检测报告当前状态为「{current}」，仅「待编制」状态的报告可以提交编制"
            return None, f"检测报告当前状态为「{current}」，不能{action}"

        entry["status"] = target
        entry["pending"] = target in PENDING_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"检测报告已{action}"
