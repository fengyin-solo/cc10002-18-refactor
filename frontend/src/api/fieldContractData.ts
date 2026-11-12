/**
 * 此文件由 backend/app/contracts/codegen_ts.py 自动生成，请勿手工修改。
 * 字段描述的单一所有者是 backend/app/contracts/declarations.py；
 * 修改字段请改后端声明后重新生成本文件。
 */
import type { ModuleDeclarationData } from './fieldContracts'


const dimensionDeclarations: ModuleDeclarationData = {
  displayName: "分析维度",
  fields: [
    { storageKey: "维度编号", label: "维度编号", required: true, fieldIndex: 0 },
    { storageKey: "维度名称", label: "维度名称", required: true, fieldIndex: 1 },
    { storageKey: "数据来源表", label: "数据来源表", required: true, fieldIndex: 2 },
    { storageKey: "维度键列", label: "维度键列", fieldIndex: 3 },
    { storageKey: "层级关系", label: "层级关系", fieldIndex: 4 },
    { storageKey: "历史拉链策略", label: "历史拉链策略", fieldIndex: 5 },
    { storageKey: "刷新周期", label: "刷新周期", fieldIndex: 6 },
    { storageKey: "默认取值", label: "默认取值", fieldIndex: 7 },
  ],
}

const datamodelDeclarations: ModuleDeclarationData = {
  displayName: "模型定义",
  fields: [
    { storageKey: "模型编号", label: "模型编号", required: true, fieldIndex: 0 },
    { storageKey: "模型名称", label: "模型名称", required: true, fieldIndex: 1 },
    { storageKey: "事实表名", label: "事实表名", required: true, fieldIndex: 2 },
    { storageKey: "关联维度", label: "关联维度", fieldIndex: 3 },
    { storageKey: "度量列定义", label: "度量列定义", fieldIndex: 4 },
    { storageKey: "分区字段", label: "分区字段", fieldIndex: 5 },
    { storageKey: "增量键", label: "增量键", fieldIndex: 6 },
    { storageKey: "刷新周期", label: "刷新周期", fieldIndex: 7 },
  ],
}

// 供前端契约编译器消费的声明数据，结构与后端 MODULE_DECLARATIONS 对齐。
export const fieldDeclarationData = Object.freeze({
  dimension: dimensionDeclarations,
  datamodel: datamodelDeclarations,
})
