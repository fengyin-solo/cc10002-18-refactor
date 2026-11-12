"""对照重构前后的真实请求快照：通过 ASGI 客户端打真实路由，落盘 JSON 供前后比对。

环境变量（均有默认值，可直接运行）：
  BACKEND_PATH  被测后端代码目录，默认 ../backend
  SNAPSHOT_PATH 快照输出路径，默认 /tmp/field-contract-snapshot.json

比对方法：分别用重构前（git worktree 检出的旧代码）与重构后的 BACKEND_PATH
各跑一次、写到不同 SNAPSHOT_PATH，再逐字节比较两个 JSON。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, os.environ.get("BACKEND_PATH", str(DEFAULT_BACKEND)))

from fastapi.testclient import TestClient

from app.main import app
from app.store import store

client = TestClient(app)
snapshot: dict = {}

for module, keyword_field, required in [
    ("dimension", "维度编号", ["维度编号", "维度名称", "数据来源表"]),
    ("datamodel", "模型编号", ["模型编号", "模型名称", "事实表名"]),
]:
    rec: dict = {"module": module}
    rec["list_default"] = client.get(f"/api/{module}").json()
    rec["list_page2"] = client.get(f"/api/{module}", params={"page": 2, "size": 2}).json()
    rec["list_size_overflow_status"] = client.get(f"/api/{module}", params={"size": 201}).status_code
    rec["list_keyword"] = client.get(f"/api/{module}", params={"keyword": "0002"}).json()
    rec["list_status"] = client.get(f"/api/{module}", params={"status": "草稿"}).json()
    rec["detail_1"] = client.get(f"/api/{module}/1").json()
    rec["detail_missing"] = {
        "status": client.get(f"/api/{module}/9999").status_code,
        "body": client.get(f"/api/{module}/9999").json(),
    }

    # 存储层历史未知键/额外属性：直接写进仓库后必须能被原接口原样读出
    rows = store.rows(module)
    rows[0]["历史遗留键"] = "legacy-value"
    rows[0]["field_9"] = "numeric-legacy"
    rec["detail_with_unknown_keys"] = client.get(f"/api/{module}/1").json()
    del rows[0]["历史遗留键"]
    del rows[0]["field_9"]

    # 正常登记：保存字段集合必须精确
    ok_payload = {v: f"{v}-值{x}" for x, v in enumerate(required)}
    ok_payload["未接入的可选字段"] = "should-not-save"
    ok_payload["field_0"] = "must-not-become-storage-key"
    resp = client.post(f"/api/{module}", json={"values": ok_payload})
    rec["create_ok"] = {"status": resp.status_code, "body": resp.json()}
    new_id = resp.json()["entry"]["id"]
    rec["create_saved_keys"] = sorted(resp.json()["entry"].keys())

    # 缺必填：中文缺失说明
    rec["create_missing"] = client.post(
        f"/api/{module}", json={"values": {required[0]: "x"}}
    ).json()

    # 动作范围
    action_results = {}
    for action in (["提交审核", "生效启用", "废弃下线"] if module == "dimension"
                   else ["提交审核", "生效发布", "废弃下线"]):
        action_results[action] = client.post(
            f"/api/{module}/{new_id}/actions", json={"values": {"action": action}}
        ).json()
    action_results["非法动作"] = client.post(
        f"/api/{module}/{new_id}/actions", json={"values": {"action": "删除"}}
    ).json()
    rec["actions"] = action_results
    rec["action_missing_entry"] = client.post(
        f"/api/{module}/9999/actions", json={"values": {"action": "提交审核"}}
    ).json()
    export_resp = client.get(f"/api/{module}/export")
    rec["export"] = {"status": export_resp.status_code, "body": export_resp.json()}
    snapshot[module] = rec

import os
snapshot_path = os.environ.get("SNAPSHOT_PATH", "/tmp/field-contract-snapshot.json")
with open(snapshot_path, "w", encoding="utf-8") as fh:
    json.dump(snapshot, fh, ensure_ascii=False, indent=2, sort_keys=True)
print(json.dumps({m: {"saved": r["create_saved_keys"], "missing": r["create_missing"]}
                  for m, r in snapshot.items()}, ensure_ascii=False, indent=2))
