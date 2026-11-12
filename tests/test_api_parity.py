"""HTTP 契约回归：重构后真实请求的地址、动作范围、分页与登记保存集合必须与原实体一致。

重点核对兼容性要求：
* 历史字段、未知中文键和额外属性（含 field_数字 形态）仍能被原接口原样读出；
* field_数字 只是说明模型属性，登记时不会成为新存储键覆盖中文原值；
* 登记实际保存的字段集合与缺失字段报错口径不变；
* 分页结果、过滤口径、动作接受范围与历史行为逐字节一致。
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import DatamodelEntry, DimensionEntry
from app.store import store

client = TestClient(app)

MODULES = {
    "dimension": {
        "required": ["维度编号", "维度名称", "数据来源表"],
        "actions": ["提交审核", "生效启用", "废弃下线"],
        "list_fields": ["维度编号", "维度名称", "数据来源表", "维度键列",
                        "层级关系", "历史拉链策略", "刷新周期", "默认取值"],
        "missing_entity": "分析维度",
    },
    "datamodel": {
        "required": ["模型编号", "模型名称", "事实表名"],
        "actions": ["提交审核", "生效发布", "废弃下线"],
        "list_fields": ["模型编号", "模型名称", "事实表名", "关联维度",
                        "度量列定义", "分区字段", "增量键", "刷新周期"],
        "missing_entity": "模型定义",
    },
}


@pytest.fixture(autouse=True)
def restore_store():
    """每个用例前后把内存仓库恢复到种子状态，避免用例间相互污染。"""
    snapshot = {name: [copy.deepcopy(row) for row in rows]
                for name, rows in store._tables.items()}
    yield
    store._tables = {name: [copy.deepcopy(row) for row in rows]
                     for name, rows in snapshot.items()}


@pytest.mark.parametrize("module", MODULES)
class TestHttpParity:
    def test_list_paging_shape_and_keys(self, module):
        spec = MODULES[module]
        resp = client.get(f"/api/{module}")
        assert resp.status_code == 200
        payload = resp.json()
        assert set(payload) == {"items", "total", "page", "size"}
        assert payload["page"] == 1 and payload["size"] == 20
        assert payload["total"] == len(payload["items"]) == 3
        # 每行只含种子键：8 个中文业务键 + id/status/pending/abnormal。
        for item in payload["items"]:
            assert set(item) == set(spec["list_fields"]) | {
                "id", "status", "pending", "abnormal"}

    def test_paging_slice_unchanged(self, module):
        page1 = client.get(f"/api/{module}", params={"page": 1, "size": 2}).json()
        page2 = client.get(f"/api/{module}", params={"page": 2, "size": 2}).json()
        assert len(page1["items"]) == 2 and len(page2["items"]) == 1
        assert page1["total"] == page2["total"] == 3
        assert page1["items"][0]["id"] != page2["items"][0]["id"]
        assert client.get(f"/api/{module}", params={"size": 201}).status_code == 400

    def test_keyword_and_status_filter(self, module):
        keyword_field = MODULES[module]["list_fields"][0]
        hit = client.get(f"/api/{module}", params={"keyword": "0002"}).json()
        assert hit["total"] == 1 and keyword_field in hit["items"][0]
        draft = client.get(f"/api/{module}", params={"status": "草稿"}).json()
        assert draft["total"] == 1 and draft["items"][0]["status"] == "草稿"

    def test_unknown_chinese_key_and_field_numeric_passthrough(self, module):
        rows = store.rows(module)
        rows[0]["历史遗留键"] = "legacy-value"
        rows[0]["field_9"] = "numeric-legacy"
        rows[0]["额外属性"] = {"nested": [1, 2]}

        detail = client.get(f"/api/{module}/1").json()
        assert detail["历史遗留键"] == "legacy-value"
        assert detail["field_9"] == "numeric-legacy"
        assert detail["额外属性"] == {"nested": [1, 2]}

        listed = client.get(f"/api/{module}").json()["items"][0]
        assert listed["历史遗留键"] == "legacy-value"
        assert listed["field_9"] == "numeric-legacy"

    def test_create_saves_exactly_required_chinese_keys(self, module):
        spec = MODULES[module]
        values = {key: f"{key}-值" for key in spec["required"]}
        # 尚未接入的可选字段与 field_数字 都不允许被登记保存。
        values["未接入的可选字段"] = "should-not-save"
        values["field_0"] = "must-not-become-storage-key"
        values["field_7"] = "same-here"

        resp = client.post(f"/api/{module}", json={"values": values})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and body["message"].endswith("已登记")
        entry = body["entry"]
        assert set(entry) == set(spec["required"]) | {
            "id", "status", "pending", "abnormal"}
        assert entry["status"] == "草稿" and entry["pending"] is True
        assert entry["abnormal"] is False
        assert "field_0" not in entry and "field_7" not in entry
        assert "未接入的可选字段" not in entry
        for key in spec["required"]:
            assert entry[key] == f"{key}-值"

    def test_missing_required_reports_chinese_names_in_order(self, module):
        spec = MODULES[module]
        resp = client.post(f"/api/{module}", json={"values": {spec["required"][0]: "x"}})
        body = resp.json()
        assert body["ok"] is False and body["entry"] is None
        assert body["message"] == "缺少必填字段：" + "、".join(spec["required"][1:])

    def test_blank_required_treated_as_missing(self, module):
        spec = MODULES[module]
        values = {key: "   " for key in spec["required"]}
        body = client.post(f"/api/{module}", json={"values": values}).json()
        assert body["ok"] is False
        assert body["message"] == "缺少必填字段：" + "、".join(spec["required"])

    def test_action_range_and_messages(self, module):
        spec = MODULES[module]
        created = client.post(
            f"/api/{module}",
            json={"values": {key: f"{key}-v" for key in spec["required"]}},
        ).json()["entry"]
        entry_id = created["id"]
        for action in spec["actions"]:
            body = client.post(
                f"/api/{module}/{entry_id}/actions",
                json={"values": {"action": action}},
            ).json()
            assert body["ok"] is True and body["message"].endswith(action)
        illegal = client.post(
            f"/api/{module}/{entry_id}/actions",
            json={"values": {"action": "删除"}},
        ).json()
        assert illegal["ok"] is False
        assert "不属于" in illegal["message"] and "删除" in illegal["message"]

    def test_action_on_missing_entry(self, module):
        body = client.post(
            f"/api/{module}/9999/actions",
            json={"values": {"action": MODULES[module]["actions"][0]}},
        ).json()
        assert body["ok"] is False
        assert MODULES[module]["missing_entity"] in body["message"]

    def test_detail_missing_returns_404(self, module):
        resp = client.get(f"/api/{module}/9999")
        assert resp.status_code == 404
        assert MODULES[module]["missing_entity"] in resp.json()["detail"]

    def test_export_route_quirk_preserved(self, module):
        # 历史现状：/export 注册在 /{entry_id} 之后，被整型路径参数拦截返回 422。
        # 重构不得顺手修复或改变该既有行为，保持 HTTP 地址与响应完全一致。
        resp = client.get(f"/api/{module}/export")
        assert resp.status_code == 422


class TestLegacyEntryModels:
    def test_dimension_entry_shape(self):
        assert list(DimensionEntry.model_fields) == [f"field_{i}" for i in range(8)]
        parsed = DimensionEntry(field_0="编号", field_7="默认")
        assert parsed.field_0 == "编号" and parsed.field_7 == "默认"
        assert parsed.field_1 is None
        dumped = parsed.model_dump()
        assert set(dumped) == {f"field_{i}" for i in range(8)}
        # 中文键作为属性传入时与旧手写类一样被忽略，不会生成中文属性。
        assert "维度编号" not in DimensionEntry(维度编号="x").model_dump()

    def test_datamodel_entry_shape(self):
        assert list(DatamodelEntry.model_fields) == [f"field_{i}" for i in range(8)]
        assert DatamodelEntry(field_2="事实表").field_2 == "事实表"

    def test_legacy_module_aliases_unchanged(self):
        from app.routers import datamodel as router_datamodel
        from app.routers import dimension as router_dimension
        from app.services import datamodel as service_datamodel
        from app.services import dimension as service_dimension

        assert router_dimension.LIST_FIELDS == MODULES["dimension"]["list_fields"]
        assert router_datamodel.LIST_FIELDS == MODULES["datamodel"]["list_fields"]
        assert service_dimension.REQUIRED_FIELDS == MODULES["dimension"]["required"]
        assert service_datamodel.REQUIRED_FIELDS == MODULES["datamodel"]["required"]
