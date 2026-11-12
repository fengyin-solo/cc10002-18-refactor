"""数据建模业务规则：状态流转、字段校验与筛选口径都收在这里。

字段口径不再本地抄写：中文存储键、必填集合与检索字段均消费字段契约的只读快照，
本服务只负责业务规则。契约未声明的历史键/额外属性不经手、不过滤，由仓库原样保留。
"""
from __future__ import annotations

from typing import Any

from app.contracts import load_contracts
from app.store import store

MODULE = "datamodel"
CONTRACT = load_contracts().get(MODULE)

# 兼容历史模块级常量的派生别名：值来自契约，不再是第二份手写描述。
REQUIRED_FIELDS = list(CONTRACT.required_storage_keys)
KEYWORD_FIELD = CONTRACT.keyword_storage_key

STATUS_ORDER = ["草稿", "待审核", "已生效", "已废弃"]
ACTION_RULES = {"提交审核": "待审核", "生效发布": "已生效", "废弃下线": "已废弃"}
NEGATIVE_ACTIONS = []


class DatamodelService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(KEYWORD_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        # 只按契约声明的必填中文存储键校验并保存；field_数字、未接入的可选字段
        # 以及任何未知键都不会进入登记结果。
        required_fields = CONTRACT.required_storage_keys
        missing = [field for field in required_fields if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in required_fields})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"模型定义 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据建模可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"模型定义已{action}"
