# 数据指标分析平台

面向指标口径定义、多维度聚合分析、AB实验评估、数据服务发布与数据应用交付的数据指标分析平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装与字段契约镜像
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   ├── app/contracts/        字段契约：声明、编译器、注册表与前端代码生成
│   └── app/store.py          内存数据仓库与示例数据
├── tests/                    契约编译、装载边界与 HTTP 行为回归
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metricdef` | 指标口径 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、数据来源表 |
| 数据源连接 | `datasource` | 数据源配置 | 配置编号、连接类型、接入地址 |
| 聚合查询 | `aggregation` | 聚合规则 | 规则编号、聚合函数、目标指标 |
| 分析看板 | `dashboard` | 看板配置 | 看板编号、看板名称、关联指标 |
| 分群分析 | `cohort` | 用户分群 | 分群编号、分群名称、筛选条件 |
| AB实验 | `abtest` | 实验方案 | 方案编号、实验名称、对照组配置 |
| 分析报告 | `report` | 报告模板 | 模板编号、模板名称、包含指标 |
| 指标预警 | `alert` | 预警规则 | 规则编号、关联指标、阈值上界 |
| 数据挖掘 | `datamine` | 挖掘任务 | 任务编号、输入数据集、算法类型 |
| 数据API | `api` | API服务 | 服务编号、输出数据集、查询参数定义 |
| ETL任务 | `etljob` | 加工任务 | 任务编号、输入源、输出目标 |
| 数据质量 | `quality` | 质量规则 | 规则编号、校验数据集、目标字段 |
| 数据建模 | `datamodel` | 模型定义 | 模型编号、模型名称、事实表名 |
| 数据导出 | `export` | 导出任务 | 任务编号、查询SQL、导出格式 |
| 数据订阅 | `subscribe` | 订阅任务 | 任务编号、数据源标识、订阅频率 |
| 数据血缘 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 人群圈选 | `segment` | 圈选规则 | 规则编号、规则名称、筛选条件组合 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.tsx`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 字段契约（维度管理 / 数据建模）

这两个实体的字段描述有唯一所有者，路由、服务、Pydantic 明细类与前端都只消费契约，
不再各自抄写中文键、列定义或必填集合。

- 单一所有者：`backend/app/contracts/declarations.py`。每个字段在此一次性声明
  中文存储键（`storage_key`，历史落库/接口数据里的真实键）、显示含义（`label`）、
  是否必填（`required`）与旧说明模型属性序号（`field_index`）。
- 编译与装载：`compiler.py` 把声明整体编译成不可变快照，发现「多描述指向同一旧键」
  「同名描述含义冲突」等问题会汇总报错、拒绝发布半成品；`registry.py` 保证原子发布，
  重新编译失败时保留原完整契约，读者持有的快照始终稳定。
- `field_数字` 只是 Pydantic 明细类（说明模型）的属性名，由契约按 `field_index`
  生成，绝不作为存储键，登记与读取始终使用中文存储键；未知中文键和额外属性原样透传。
- 前端镜像：`frontend/src/api/fieldContractData.ts` 由
  `python -m app.contracts.codegen_ts`（在 `backend` 目录执行）从同一份声明生成，
  `fieldContracts.ts` 负责编译冻结。改字段只改后端声明并重新生成，手工改镜像会被
  `tests/test_frontend_mirror.py` 的逐字节比对拦下。
- 回归测试：`python -m pytest tests` 覆盖真实请求前后对照、冲突显式上报、初始化失败
  保留旧契约与并发只发布一份完整版本等兼容性场景。

领域：数据工程
子方向：数据分析与数据应用
