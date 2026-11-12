/**
 * 字段契约的前端编译器：把自动生成的声明数据（见 fieldContractData.ts）整体编译
 * 成不可变快照，供页面消费。字段描述的单一所有者在后端
 * backend/app/contracts/declarations.py，前端不允许手写第二份声明。
 *
 * 边界约束：
 *  - storageKey 是历史数据里真实存在的中文键，唯一的存储身份；
 *  - label 只负责界面显示；required 只描述登记口径（与后端契约保持一致）；
 *  - fieldIndex 对应后端旧说明模型的 field_数字 属性，仅作兼容说明，
 *    前端绝不能把它当成新存储键去读取或提交；
 *  - 契约在模块加载时一次性整体编译并 Object.freeze，任何冲突都会拒绝发布，
 *    消费者拿到的是稳定快照，无法通过修改契约对象反向影响另一个模块。
 */
import { fieldDeclarationData } from './fieldContractData'

export interface FieldDeclaration {
  /** 历史中文存储键：接口数据的真实键名，唯一存储身份。 */
  storageKey: string
  /** 显示含义：表头、筛选项等界面渲染使用。 */
  label: string
  /** 登记时是否必填，规则与后端字段契约一致。 */
  required?: boolean
  /** 后端 Pydantic 说明模型的 field_数字 序号，仅作兼容说明，不是存储键。 */
  fieldIndex?: number
}

export interface ModuleDeclarationData {
  displayName: string
  fields: readonly FieldDeclaration[]
}

export interface FieldContract {
  /** 历史中文存储键：接口数据的真实键名，唯一存储身份。 */
  storageKey: string
  /** 显示含义：表头、筛选项等界面渲染使用。 */
  label: string
  /** 登记时是否必填，规则与后端字段契约一致。 */
  required: boolean
  /** 后端 Pydantic 说明模型的 field_数字 序号，无对应属性时为 null，不是存储键。 */
  fieldIndex: number | null
  /** 旧说明模型属性名（field_数字），仅用于说明，不参与数据读写。 */
  modelAttribute: `field_${number}` | null
}

export interface ModuleContract {
  /** 模块标识，对应后端模块名与接口前缀。 */
  module: string
  /** 实体显示名。 */
  displayName: string
  /** 按声明顺序排列的只读字段契约。 */
  fields: readonly FieldContract[]
  /** 全部中文存储键，即历史展示列。 */
  storageKeys: readonly string[]
  /** 全部显示名。 */
  labels: readonly string[]
  /** 登记必填的中文存储键。 */
  requiredKeys: readonly string[]
  /** 按中文存储键取显示含义；未知历史键回退为键名本身，保证旧数据仍可渲染。 */
  labelFor: (storageKey: string) => string
}

/** 编译期冲突：契约不允许静默选最后一个描述，发现问题直接显式报错。 */
export class ContractConflictError extends Error {
  constructor(public readonly conflicts: string[]) {
    super(`字段契约编译失败，已拒绝发布半成品：\n - ${conflicts.join('\n - ')}`)
    this.name = 'ContractConflictError'
  }
}

/** 编译单个模块的声明为冻结契约；单模块冲突时整体抛出，不产出半成品。 */
export function freezeModule(
  module: string,
  displayName: string,
  declarations: readonly FieldDeclaration[],
): ModuleContract {
  const conflicts: string[] = []
  const seenKeys = new Map<string, string>()
  const seenLabels = new Map<string, string>()
  const seenIndexes = new Map<number, string>()

  if (declarations.length === 0) {
    conflicts.push(`模块「${module}」没有任何字段声明，拒绝空契约发布`)
  }

  const fields: FieldContract[] = declarations.map((declaration, position) => {
    const descriptor = `第 ${position + 1} 个字段（显示名「${declaration.label}」）`
    if (!declaration.storageKey.trim()) {
      conflicts.push(`模块「${module}」${descriptor}的中文存储键为空，存储键不允许空缺`)
    }
    if (!declaration.label.trim()) {
      conflicts.push(
        `模块「${module}」存储键「${declaration.storageKey}」的显示含义为空，显示名不允许空缺`,
      )
    }
    if (seenKeys.has(declaration.storageKey)) {
      conflicts.push(
        `模块「${module}」字段声明冲突：存储键「${declaration.storageKey}」同时被` +
          `${descriptor}与「${seenKeys.get(declaration.storageKey)}」指向，拒绝静默取最后一个`,
      )
    }
    if (seenLabels.has(declaration.label)) {
      conflicts.push(
        `模块「${module}」字段声明冲突：显示名「${declaration.label}」被存储键` +
          `「${seenLabels.get(declaration.label)}」与「${declaration.storageKey}」重复使用`,
      )
    }
    if (declaration.fieldIndex !== undefined) {
      if (declaration.fieldIndex < 0) {
        conflicts.push(`模块「${module}」${descriptor}的 field 序号非法，必须从 0 开始`)
      } else if (seenIndexes.has(declaration.fieldIndex)) {
        conflicts.push(
          `模块「${module}」字段声明冲突：field_${declaration.fieldIndex} 同时映射到` +
            `「${seenIndexes.get(declaration.fieldIndex)}」与「${declaration.storageKey}」`,
        )
      }
      seenIndexes.set(declaration.fieldIndex, declaration.storageKey)
    }
    seenKeys.set(declaration.storageKey, declaration.label)
    seenLabels.set(declaration.label, declaration.storageKey)

    return Object.freeze({
      storageKey: declaration.storageKey,
      label: declaration.label,
      required: declaration.required ?? false,
      fieldIndex: declaration.fieldIndex ?? null,
      modelAttribute:
        declaration.fieldIndex === undefined
          ? null
          : (`field_${declaration.fieldIndex}` as `field_${number}`),
    })
  })

  if (conflicts.length > 0) {
    throw new ContractConflictError(conflicts)
  }

  const labelByKey = new Map(fields.map((item) => [item.storageKey, item.label] as const))
  const contract: Readonly<ModuleContract> = {
    module,
    displayName,
    fields: Object.freeze(fields),
    storageKeys: Object.freeze(fields.map((item) => item.storageKey)),
    labels: Object.freeze(fields.map((item) => item.label)),
    requiredKeys: Object.freeze(
      fields.filter((item) => item.required).map((item) => item.storageKey),
    ),
    labelFor: (storageKey: string) => labelByKey.get(storageKey) ?? storageKey,
  }
  return Object.freeze(contract)
}

/**
 * 整体编译所有模块：与后端编译器保持同一套跨模块口径——同名必须同义。
 * 任一模块或跨模块检查失败都抛出冲突，不发布任何半成品契约。
 */
function compileAll(
  data: Readonly<Record<string, ModuleDeclarationData>>,
): Readonly<Record<string, ModuleContract>> {
  const keyOwners = new Map<string, Set<string>>()
  const labelOwners = new Map<string, Set<string>>()
  const compiled: Record<string, ModuleContract> = {}

  for (const moduleName of Object.keys(data)) {
    const { displayName, fields } = data[moduleName]
    const contract = freezeModule(moduleName, displayName, fields)
    compiled[moduleName] = contract
    for (const item of contract.fields) {
      if (!keyOwners.has(item.storageKey)) keyOwners.set(item.storageKey, new Set())
      keyOwners.get(item.storageKey)!.add(item.label)
      if (!labelOwners.has(item.label)) labelOwners.set(item.label, new Set())
      labelOwners.get(item.label)!.add(item.storageKey)
    }
  }

  const conflicts: string[] = []
  for (const [key, labels] of keyOwners) {
    if (labels.size > 1) {
      conflicts.push(`跨模块字段冲突：存储键「${key}」在不同实体中含义不一致，拒绝静默合并`)
    }
  }
  for (const [label, keys] of labelOwners) {
    if (keys.size > 1) {
      conflicts.push(`跨模块字段冲突：显示名「${label}」指向了不同的旧存储键，同名描述不允许漂移`)
    }
  }
  if (conflicts.length > 0) {
    throw new ContractConflictError(conflicts)
  }
  return Object.freeze(compiled)
}

/** 模块级只读契约目录：一次性整体编译、整体冻结，不提供局部修改入口。 */
export const fieldContracts = compileAll(
  fieldDeclarationData as Readonly<Record<string, ModuleDeclarationData>>,
)

export type FieldContractModule = keyof typeof fieldContracts
