"""字段契约声明：维度管理与数据建模两个模块的字段描述唯一所有者。

历史上同一份字段描述被抄写了四遍：
  * 前端页面的列定义（中文键同时充当存储键与表头）；
  * 路由层的 ``LIST_FIELDS``（展示列）；
  * 服务层的 ``REQUIRED_FIELDS``（登记必填、实际保存集合）；
  * ``app/schemas.py`` 里 Pydantic 明细类的 ``field_数字`` 属性（说明模型）。

重构后各模块在这里一次性声明自己的字段契约，其余各层（路由、服务、Pydantic
明细类、前端）只消费编译产物，不再各自猜测字段之间的对应关系。

声明中的三个概念边界是明确的：
  * ``storage_key``——历史存储键，即落库/接口数据里真实存在的中文键。它是唯一的
    存储身份，``field_数字`` 只是说明模型（Pydantic 明细类）的属性名，绝不允许
    反过来成为新存储键覆盖中文原值；
  * ``label``——显示含义，用于表头、筛选标签等界面渲染；
  * ``required``——登记时是否必填（沿用重构前的必填规则，只有前三个字段必填）。

未知中文键、历史遗留的额外属性不在这里声明，存储与读取链路会原样透传，契约
不负责枚举它们。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldDeclaration:
    """单个字段的声明：存储键、显示含义与必填规则都归这一个对象所有。"""

    storage_key: str
    label: str
    required: bool = False
    # 既有 Pydantic 明细类里的属性序号（field_0、field_1……），仅用于兼容旧说明模型，
    # 不是存储键。None 表示该字段在旧明细类里没有对应属性。
    field_index: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class ModuleDeclaration:
    """单个业务模块的完整字段声明。"""

    name: str
    display_name: str
    fields: tuple[FieldDeclaration, ...] = field(default_factory=tuple)

    def with_fields(self, *fields_: FieldDeclaration) -> "ModuleDeclaration":
        return ModuleDeclaration(
            name=self.name,
            display_name=self.display_name,
            fields=tuple(fields_),
        )


# ---------------------------------------------------------------------------
# 维度管理：中文存储键、显示含义与必填规则（前三个必填，其余为历史可选字段）。
# ---------------------------------------------------------------------------
DIMENSION_DECLARATION = ModuleDeclaration(
    name="dimension",
    display_name="分析维度",
).with_fields(
    FieldDeclaration("维度编号", "维度编号", required=True, field_index=0),
    FieldDeclaration("维度名称", "维度名称", required=True, field_index=1),
    FieldDeclaration("数据来源表", "数据来源表", required=True, field_index=2),
    FieldDeclaration("维度键列", "维度键列", field_index=3),
    FieldDeclaration("层级关系", "层级关系", field_index=4),
    FieldDeclaration("历史拉链策略", "历史拉链策略", field_index=5),
    FieldDeclaration("刷新周期", "刷新周期", field_index=6),
    FieldDeclaration("默认取值", "默认取值", field_index=7),
)

# ---------------------------------------------------------------------------
# 数据建模：注意「刷新周期」与维度管理中的同名字段分属两个实体，含义各自独立，
# 跨模块不允许互相借用或覆盖（编译期会做冲突检查）。
# ---------------------------------------------------------------------------
DATAMODEL_DECLARATION = ModuleDeclaration(
    name="datamodel",
    display_name="模型定义",
).with_fields(
    FieldDeclaration("模型编号", "模型编号", required=True, field_index=0),
    FieldDeclaration("模型名称", "模型名称", required=True, field_index=1),
    FieldDeclaration("事实表名", "事实表名", required=True, field_index=2),
    FieldDeclaration("关联维度", "关联维度", field_index=3),
    FieldDeclaration("度量列定义", "度量列定义", field_index=4),
    FieldDeclaration("分区字段", "分区字段", field_index=5),
    FieldDeclaration("增量键", "增量键", field_index=6),
    FieldDeclaration("刷新周期", "刷新周期", field_index=7),
)


#: 参与统一编译的模块声明集合。顺序即对外暴露的稳定顺序。
MODULE_DECLARATIONS: tuple[ModuleDeclaration, ...] = (
    DIMENSION_DECLARATION,
    DATAMODEL_DECLARATION,
)
