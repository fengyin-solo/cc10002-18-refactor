"""契约编译器测试：冲突显式上报、全有或全无、快照冻结与 field_数字 边界。"""
from __future__ import annotations

import pytest

from app.contracts import (
    ContractConflictError,
    FieldDeclaration,
    ModuleDeclaration,
)
from app.contracts.compiler import compile_contracts
from app.contracts.declarations import (
    DATAMODEL_DECLARATION,
    DIMENSION_DECLARATION,
)


def field(key: str, label: str | None = None, *, required: bool = False,
          index: int | None = None) -> FieldDeclaration:
    return FieldDeclaration(key, label if label is not None else key,
                            required=required, field_index=index)


def module(name: str, *fields_: FieldDeclaration, display: str | None = None) -> ModuleDeclaration:
    return ModuleDeclaration(name=name, display_name=display or name,
                             fields=tuple(fields_))


class TestHappyPath:
    def test_official_declarations_compile(self):
        snapshot = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        assert snapshot.names() == ("dimension", "datamodel")

        dim = snapshot.get("dimension")
        assert dim.storage_keys == (
            "维度编号", "维度名称", "数据来源表", "维度键列",
            "层级关系", "历史拉链策略", "刷新周期", "默认取值",
        )
        assert dim.required_storage_keys == ("维度编号", "维度名称", "数据来源表")
        assert dim.keyword_storage_key == "维度编号"
        assert dim.labels == dim.storage_keys  # 本项目显示名与存储键同名

        model = snapshot.get("datamodel")
        assert model.required_storage_keys == ("模型编号", "模型名称", "事实表名")
        assert model.keyword_storage_key == "模型编号"

    def test_field_index_maps_back_to_chinese_key(self):
        snapshot = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        dim = snapshot.get("dimension")
        for i, key in enumerate(dim.storage_keys):
            contract = dim.field_by_index(i)
            assert contract is not None
            assert contract.storage_key == key
            assert contract.model_attribute == f"field_{i}"

    def test_entry_model_keeps_field_numeric_attributes_only(self):
        snapshot = compile_contracts((DIMENSION_DECLARATION,))
        model = snapshot.entry_model("dimension")
        assert list(model.model_fields) == [f"field_{i}" for i in range(8)]
        # 中文存储键绝不成为说明模型属性；field_数字 也绝不成为存储键。
        assert all(not key.startswith("field_") for key in
                   snapshot.get("dimension").storage_keys)

    def test_unknown_key_returns_none_for_passthrough(self):
        dim = compile_contracts((DIMENSION_DECLARATION,)).get("dimension")
        assert dim.field_by_storage_key("未登记的历史键") is None
        assert dim.field_by_label("未登记的历史键") is None
        assert dim.field_by_index(99) is None

    def test_same_name_same_meaning_across_modules_is_allowed(self):
        # 「刷新周期」在两个实体中键名与含义完全一致：允许复用，不判冲突。
        snapshot = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        assert snapshot.get("dimension").field_by_storage_key("刷新周期").label == "刷新周期"
        assert snapshot.get("datamodel").field_by_storage_key("刷新周期").label == "刷新周期"


class TestConflictReporting:
    def test_duplicate_storage_key_reports_instead_of_last_wins(self):
        decl = module("m", field("主键", index=0), field("主键", "另一描述", index=1))
        with pytest.raises(ContractConflictError) as exc:
            compile_contracts((decl,))
        message = str(exc.value)
        assert "主键" in message and "另一描述" in message
        assert "拒绝静默取最后一个" in message
        assert len(exc.value.conflicts) >= 1

    def test_duplicate_label_reports_conflict(self):
        decl = module("m", field("键A", "同名"), field("键B", "同名"))
        with pytest.raises(ContractConflictError, match="显示名"):
            compile_contracts((decl,))

    def test_duplicate_field_index_reports_conflict(self):
        decl = module("m", field("键A", index=3), field("键B", index=3))
        with pytest.raises(ContractConflictError, match="field_3"):
            compile_contracts((decl,))

    def test_negative_field_index_rejected(self):
        decl = module("m", FieldDeclaration("键A", "键A", field_index=-1))
        with pytest.raises(ContractConflictError, match="序号"):
            compile_contracts((decl,))

    def test_empty_storage_key_rejected(self):
        decl = module("m", FieldDeclaration("  ", "空键"))
        with pytest.raises(ContractConflictError, match="存储键为空"):
            compile_contracts((decl,))

    def test_empty_module_rejected(self):
        with pytest.raises(ContractConflictError, match="没有任何字段声明"):
            compile_contracts((module("empty"),))

    def test_duplicate_module_name_rejected(self):
        decl = module("same", field("键A", index=0))
        with pytest.raises(ContractConflictError, match="模块名"):
            compile_contracts((decl, decl))

    def test_cross_module_same_key_different_label_conflicts(self):
        left = module("a", field("共用键", "含义甲", index=0))
        right = module("b", field("共用键", "含义乙", index=0))
        with pytest.raises(ContractConflictError, match="跨模块字段冲突") as exc:
            compile_contracts((left, right))
        assert "含义甲" in str(exc.value) and "含义乙" in str(exc.value)

    def test_cross_module_same_label_different_key_conflicts(self):
        left = module("a", field("键甲", "同名标签", index=0))
        right = module("b", field("键乙", "同名标签", index=0))
        with pytest.raises(ContractConflictError, match="同名描述不允许在实体间漂移"):
            compile_contracts((left, right))

    def test_multiple_conflicts_are_all_reported_together(self):
        decl = module(
            "m",
            field("重复键", index=0),
            field("重复键", index=1),
            field("其他键", "重复标签", index=2),
            field("另一些键", "重复标签", index=3),
        )
        with pytest.raises(ContractConflictError) as exc:
            compile_contracts((decl,))
        assert len(exc.value.conflicts) >= 2


class TestAtomicityAndImmutability:
    def test_compile_is_all_or_nothing(self):
        good = module("good", field("键A", index=0), field("键B", index=1))
        broken = module("broken", field("重复", index=0), field("重复", index=1))
        with pytest.raises(ContractConflictError):
            compile_contracts((good, broken))
        # 编译失败不返回任何模块对象，适配层不可能拿到「另一半旧描述」的半成品。

    def test_snapshot_structure_is_frozen(self):
        snapshot = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        dim = snapshot.get("dimension")
        with pytest.raises(TypeError):
            snapshot.modules["intruder"] = dim  # type: ignore[index]
        with pytest.raises(TypeError):
            dim.storage_keys[0] = "被篡改"  # type: ignore[index]
        with pytest.raises(TypeError):
            dim.fields[0] = dim.fields[1]  # type: ignore[index]
        with pytest.raises((TypeError, AttributeError)):
            dim.fields[0].storage_key = "被篡改"  # type: ignore[misc]

    def test_consumer_mutation_cannot_reach_other_module(self):
        snapshot = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        dim_keys = snapshot.get("dimension").storage_keys
        model_keys = snapshot.get("datamodel").storage_keys
        # 消费者即使持有引用也无法改写；两个模块的契约互不影响。
        with pytest.raises(TypeError):
            dim_keys[0] = model_keys[0]  # type: ignore[index]
        assert snapshot.get("dimension").storage_keys == dim_keys
        assert snapshot.get("datamodel").storage_keys == model_keys

    def test_recompile_produces_independent_snapshot(self):
        first = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        second = compile_contracts((DIMENSION_DECLARATION, DATAMODEL_DECLARATION))
        assert first is not second
        assert first.get("dimension").storage_keys == second.get("dimension").storage_keys
        # 已持有旧快照的读者引用保持稳定。
        assert first.get("dimension") is first.get("dimension")
