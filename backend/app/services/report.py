"""报告出具业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "report"
REQUIRED_FIELDS = ["报告编号", "关联样品", "报告类型"]
STATUS_ORDER = ["待编制", "已编制", "待签发", "已出具", "已作废"]
ACTION_RULES = {"提交编制": "已编制", "确认签发": "已出具", "作废报告": "已作废"}
NEGATIVE_ACTIONS = ["作废报告"]

# 仍在流转、需要继续处理的状态；已出具/已作废都不再计入待处理（含待签发结果）。
PENDING_STATUSES = {"待编制", "已编制", "待签发"}
# 列表支持的筛选字段：报告编号、报告类型、签发人员。
FILTER_FIELDS = ["报告编号", "报告类型", "签发人员"]
VOIDED_STATUS = STATUS_ORDER[-1]


class ReportService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> tuple[list[dict[str, Any]], int, str | None]:
        """按报告编号、报告类型、签发人员与状态做 AND 过滤，再分页。

        返回 (当前页记录, 过滤后总数, 无命中时的原因说明)。
        """
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        active = {
            field: keyword.strip()
            for field, keyword in (filters or {}).items()
            if field in FILTER_FIELDS and keyword and keyword.strip()
        }
        for field, keyword in active.items():
            needle = keyword.casefold()
            rows = [
                row for row in rows
                if needle in str(row.get(field, "")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
            # 双保险：待签发等在办结果里绝不允许混入已作废报告。
            if status in PENDING_STATUSES:
                rows = [row for row in rows if row.get("status") != VOIDED_STATUS]

        total = len(rows)
        message = self._empty_message(active, status, total)
        start = (max(page, 1) - 1) * size
        return rows[start:start + size], total, message

    @staticmethod
    def _empty_message(active: dict[str, str], status: str | None, total: int) -> str | None:
        if total > 0:
            return None
        if not active and not status:
            return "暂无检测报告数据，可先登记检测报告"
        reasons = [f"{field}包含「{keyword}」" for field, keyword in active.items()]
        if status:
            reasons.append(f"报告状态为「{status}」")
        return f"没有命中的检测报告：满足 {'、'.join(reasons)} 的记录为 0 条，请调整筛选条件后重试"

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
        entry["pending"] = entry["status"] in PENDING_STATUSES
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检测报告 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于报告出具可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        # 已作废（含已出具）立即退出待处理口径，不会再残留在待签发等结果里。
        entry["pending"] = target in PENDING_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"检测报告已{action}"
