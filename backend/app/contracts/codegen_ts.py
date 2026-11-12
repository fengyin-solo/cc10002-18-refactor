"""把后端字段契约声明生成为前端镜像数据模块。

字段描述的单一所有者是 :mod:`app.contracts.declarations`；前端不允许再手写一份
声明。本脚本把声明生成为只含数据的 TypeScript 模块，前端契约编译器消费该数据。

用法（在 backend 目录下执行）::

    python -m app.contracts.codegen_ts

生成结果与仓库内已提交的镜像必须逐字节一致，偏离会被
``tests/test_frontend_mirror.py`` 拦下，防止两份描述各自漂移。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.contracts.declarations import MODULE_DECLARATIONS

_HEADER = """\
/**
 * 此文件由 backend/app/contracts/codegen_ts.py 自动生成，请勿手工修改。
 * 字段描述的单一所有者是 backend/app/contracts/declarations.py；
 * 修改字段请改后端声明后重新生成本文件。
 */
import type { ModuleDeclarationData } from './fieldContracts'
"""


def _ts_string(value: str) -> str:
    # JSON 字面量同时是合法的 TypeScript 字符串，ensure_ascii=False 保留中文可读性。
    return json.dumps(value, ensure_ascii=False)


def _module_block(module) -> str:
    const_name = f"{module.name}Declarations"
    lines = [
        f"const {const_name}: ModuleDeclarationData = {{",
        f"  displayName: {_ts_string(module.display_name)},",
        "  fields: [",
    ]
    for item in module.fields:
        parts = [
            f"storageKey: {_ts_string(item.storage_key)}",
            f"label: {_ts_string(item.label)}",
        ]
        if item.required:
            parts.append("required: true")
        if item.field_index is not None:
            parts.append(f"fieldIndex: {item.field_index}")
        lines.append("    { " + ", ".join(parts) + " },")
    lines.append("  ],")
    lines.append("}")
    return "\n".join(lines)


def render() -> str:
    blocks = [_HEADER]
    const_names = [f"{module.name}Declarations" for module in MODULE_DECLARATIONS]
    for module in MODULE_DECLARATIONS:
        blocks.append(_module_block(module))

    entries = ",\n  ".join(
        f"{module.name}: {name}"
        for module, name in zip(MODULE_DECLARATIONS, const_names)
    )
    blocks.append(
        "// 供前端契约编译器消费的声明数据，结构与后端 MODULE_DECLARATIONS 对齐。\n"
        "export const fieldDeclarationData = Object.freeze({\n"
        f"  {entries},\n"
        "})\n"
    )
    return "\n\n".join(blocks)


def default_output_path() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "fieldContractData.ts"


def main() -> None:
    output = default_output_path()
    output.write_text(render(), encoding="utf-8")
    print(f"generated {output}")


if __name__ == "__main__":
    main()
