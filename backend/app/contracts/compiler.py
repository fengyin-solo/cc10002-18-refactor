"""字段契约编译器与只读快照。

编译器把 :mod:`app.contracts.declarations` 里的声明整体编译成一份不可变快照，
适配层（路由、服务、Pydantic 明细类、前端契约镜像）只消费快照，不直接读声明。

设计约束（对应重构的兼容性要求）：

* **整体边界、全有或全无**。一次编译覆盖所有模块，任何冲突都会让整次编译失败，
  不会出现「维度一半用新描述、建模另一半仍用旧描述」的半成品；失败时旧快照原样
  保留，由 :class:`~app.contracts.registry.ContractRegistry` 负责发布策略。
* **冲突显式上报，禁止静默覆盖**。同一模块内多个描述指向同一旧存储键、显示名
  重复、属性序号重复，以及跨模块同名描述含义不一致，都会汇总进
  :class:`ContractConflictError` 一次性抛出，而不是静默选最后一个。
* **快照稳定且不可变**。发布出去的是冻结对象（``frozen`` 数据类、元组、只读
  映射），外部消费者拿到后无法反向修改另一个模块的行为。
* **``field_数字`` 只是说明模型属性**。它用于生成兼容旧形态的 Pydantic 明细类，
  不参与存储键解析，更不能覆盖中文存储键。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import create_model

from app.contracts.declarations import FieldDeclaration, ModuleDeclaration


class ContractConflictError(ValueError):
    """声明存在冲突、无法编译出完整契约时抛出，消息里逐条列出全部冲突。"""

    def __init__(self, conflicts: list[str]) -> None:
        self.conflicts = list(conflicts)
        super().__init__("字段契约编译失败，已拒绝发布半成品：\n - " + "\n - ".join(conflicts))


@dataclass(frozen=True)
class FieldContract:
    """单个字段编译后的只读契约：存储身份、显示含义、必填规则、旧属性序号。"""

    storage_key: str
    label: str
    required: bool
    field_index: int | None
    description: str | None

    @property
    def model_attribute(self) -> str | None:
        """旧 Pydantic 明细类上的属性名（field_数字），没有序号时为 ``None``。"""
        if self.field_index is None:
            return None
        return f"field_{self.field_index}"


@dataclass(frozen=True)
class ModuleContract:
    """单个模块编译后的只读字段契约。"""

    name: str
    display_name: str
    fields: tuple[FieldContract, ...]
    entry_model: type
    _by_storage_key: Mapping[str, FieldContract]
    _by_label: Mapping[str, FieldContract]
    _by_field_index: Mapping[int, FieldContract]

    @property
    def storage_keys(self) -> tuple[str, ...]:
        """按声明顺序排列的全部中文存储键（即历史列表展示列）。"""
        return tuple(item.storage_key for item in self.fields)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(item.label for item in self.fields)

    @property
    def required_storage_keys(self) -> tuple[str, ...]:
        """登记必填且会实际保存的中文存储键，顺序与历史 REQUIRED_FIELDS 一致。"""
        return tuple(item.storage_key for item in self.fields if item.required)

    @property
    def keyword_storage_key(self) -> str:
        """列表关键字检索所依据的字段，即模块声明中的第一个字段。"""
        return self.fields[0].storage_key

    def field_by_storage_key(self, storage_key: str) -> FieldContract | None:
        """按中文存储键取字段契约；未知历史键返回 ``None``，由调用方原样透传。"""
        return self._by_storage_key.get(storage_key)

    def field_by_label(self, label: str) -> FieldContract | None:
        return self._by_label.get(label)

    def field_by_index(self, index: int) -> FieldContract | None:
        return self._by_field_index.get(index)


@dataclass(frozen=True)
class ContractsSnapshot:
    """一次成功编译发布的完整契约快照；所有模块同生共死，不允许局部更新。"""

    modules: Mapping[str, ModuleContract]
    order: tuple[str, ...]

    def get(self, module_name: str) -> ModuleContract:
        return self.modules[module_name]

    def names(self) -> tuple[str, ...]:
        return self.order

    def entry_model(self, module_name: str) -> type:
        return self.modules[module_name].entry_model


_ENTRY_MODEL_NAMES = {
    "dimension": "Dimension",
    "datamodel": "Datamodel",
}


def _build_entry_model(module: ModuleDeclaration, fields: tuple[FieldContract, ...]) -> type:
    """按旧说明模型的形态生成 Pydantic 明细类：field_0..field_n 均为可选字符串。

    生成的类只承担「说明模型」角色，属性名不会出现在任何存储/接口数据里。
    """
    attributes: dict[str, Any] = {
        item.model_attribute: (str | None, None)
        for item in fields
        if item.field_index is not None
    }
    model = create_model(
        f"{module.name.capitalize()}Entry",
        __doc__=f"{module.display_name}明细结构（由字段契约编译生成，属性仅为说明模型）。",
        **attributes,
    )
    # create_model 使用 type 的类名规则，这里显式对齐历史明细类命名。
    model.__name__ = f"{_ENTRY_MODEL_NAMES.get(module.name, module.name.capitalize())}Entry"
    return model


def compile_contracts(declarations: tuple[ModuleDeclaration, ...]) -> ContractsSnapshot:
    """把全部模块声明整体编译成不可变快照；发现任何冲突都整体失败。

    冲突检查覆盖：
      1. 模块名重复、字段存储键为空；
      2. 同一模块内多个描述指向同一旧存储键（拒绝静默选最后一个）；
      3. 同一模块内显示名重复、``field_数字`` 序号重复；
      4. 跨模块同名字段含义不一致（同一存储键显示名不同，或同一显示名指向不同
         存储键）；各实体独立声明、键名与含义完全一致的复用不算冲突。
    """
    conflicts: list[str] = []

    seen_module_names: dict[str, str] = {}
    # 跨模块一致性登记表：存储键 -> [(模块, 显示名, 存储键)]；显示名同理反向登记。
    global_key_labels: dict[str, list[tuple[str, str]]] = {}
    global_label_keys: dict[str, list[tuple[str, str]]] = {}

    compiled: dict[str, ModuleContract] = {}

    for module in declarations:
        if module.name in seen_module_names:
            conflicts.append(
                f"模块名「{module.name}」被重复声明（{seen_module_names[module.name]}），"
                "模块契约必须一一对应"
            )
            continue
        seen_module_names[module.name] = module.name
        if not module.fields:
            conflicts.append(f"模块「{module.name}」没有任何字段声明，拒绝空契约发布")
            continue

        # 记录本模块处理前的冲突条数，处理后用差值判断本模块是否自身冲突，
        # 不依赖消息文本匹配，避免模块名出现在别处时误判。
        conflicts_before = len(conflicts)
        by_key: dict[str, FieldContract] = {}
        by_label: dict[str, FieldContract] = {}
        by_index: dict[int, FieldContract] = {}
        ordered: list[FieldContract] = []

        for position, declaration in enumerate(module.fields, start=1):
            descriptor = f"第 {position} 个字段（显示名「{declaration.label}」）"
            key = declaration.storage_key
            if not isinstance(key, str) or not key.strip():
                conflicts.append(
                    f"模块「{module.name}」{descriptor}的中文存储键为空，"
                    "存储键是历史数据的唯一身份，不允许空缺"
                )
                continue
            if not isinstance(declaration.label, str) or not declaration.label.strip():
                conflicts.append(
                    f"模块「{module.name}」存储键「{key}」的显示含义为空，"
                    "界面渲染缺少可读名称，不允许空缺"
                )
                continue
            if key in by_key:
                conflicts.append(
                    f"模块「{module.name}」字段声明冲突：存储键「{key}」同时被"
                    f"{descriptor}与「{by_key[key].label}」指向，拒绝静默取最后一个"
                )
                continue
            if declaration.label in by_label:
                conflicts.append(
                    f"模块「{module.name}」字段声明冲突：显示名「{declaration.label}」"
                    f"被存储键「{by_label[declaration.label].storage_key}」与「{key}」"
                    "重复使用，界面渲染无法确定归属"
                )
                continue
            if declaration.field_index is not None:
                if declaration.field_index < 0:
                    conflicts.append(
                        f"模块「{module.name}」{descriptor}的 field 序号 "
                        f"{declaration.field_index} 非法，序号必须从 0 开始"
                    )
                    continue
                if declaration.field_index in by_index:
                    conflicts.append(
                        f"模块「{module.name}」字段声明冲突：field_{declaration.field_index} "
                        f"同时映射到存储键「{by_index[declaration.field_index].storage_key}」"
                        f"与「{key}」，旧明细类属性不允许一对多"
                    )
                    continue

            contract = FieldContract(
                storage_key=key,
                label=declaration.label,
                required=declaration.required,
                field_index=declaration.field_index,
                description=declaration.description,
            )
            by_key[key] = contract
            by_label[declaration.label] = contract
            if declaration.field_index is not None:
                by_index[declaration.field_index] = contract
            ordered.append(contract)
            global_key_labels.setdefault(key, []).append((module.name, declaration.label))
            global_label_keys.setdefault(declaration.label, []).append((module.name, key))

        # 单模块自身无冲突才构建，冲突模块不产出半成品。
        if len(conflicts) == conflicts_before:
            entry_model = _build_entry_model(module, tuple(ordered))
            compiled[module.name] = ModuleContract(
                name=module.name,
                display_name=module.display_name,
                fields=tuple(ordered),
                entry_model=entry_model,
                _by_storage_key=MappingProxyType(dict(by_key)),
                _by_label=MappingProxyType(dict(by_label)),
                _by_field_index=MappingProxyType(dict(by_index)),
            )

    # 跨模块含义一致性：同名必须同义，防止一个实体的描述悄悄决定另一个实体的行为。
    for key, occurrences in global_key_labels.items():
        labels = {label for _, label in occurrences}
        if len(labels) > 1:
            detail = "、".join(f"模块「{name}」显示名「{label}」" for name, label in occurrences)
            conflicts.append(
                f"跨模块字段冲突：存储键「{key}」在不同实体中含义不一致（{detail}），"
                "请在各自模块内显式区分，拒绝静默合并"
            )
    for label, occurrences in global_label_keys.items():
        keys = {key for _, key in occurrences}
        if len(keys) > 1:
            detail = "、".join(f"模块「{name}」存储键「{key}」" for name, key in occurrences)
            conflicts.append(
                f"跨模块字段冲突：显示名「{label}」指向了不同的旧存储键（{detail}），"
                "同名描述不允许在实体间漂移"
            )

    if conflicts:
        raise ContractConflictError(conflicts)

    order = tuple(module.name for module in declarations)
    return ContractsSnapshot(
        modules=MappingProxyType(compiled),
        order=order,
    )
