"""字段契约包：声明（单一所有者）→ 编译（冲突检查/不可变快照）→ 注册（原子发布）。

适配层只允许通过 :func:`get_contract` / :data:`registry` 消费只读契约，
不要直接引用声明数据，避免绕过编译期的冲突检查。
"""
from __future__ import annotations

from app.contracts.compiler import (
    ContractConflictError,
    ContractsSnapshot,
    FieldContract,
    ModuleContract,
)
from app.contracts.declarations import FieldDeclaration, ModuleDeclaration
from app.contracts.registry import (
    ContractRegistry,
    get_contract,
    load_contracts,
    registry,
)

__all__ = [
    "ContractConflictError",
    "ContractRegistry",
    "ContractsSnapshot",
    "FieldContract",
    "FieldDeclaration",
    "ModuleContract",
    "ModuleDeclaration",
    "get_contract",
    "load_contracts",
    "registry",
]
