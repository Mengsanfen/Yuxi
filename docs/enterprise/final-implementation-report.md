# 企业 Agent 最终实施报告

## 架构与改造差异

本项目是在上游 [Yuxi](https://github.com/xerrors/Yuxi) 的 LangGraph、FastAPI、Vue、RAG、MCP 和沙盒基础上进行企业客服场景二次开发。原有通用对话能力之外，现有企业请求走 `Vue -> FastAPI -> Chat Service/ARQ -> EnterpriseServiceAgent -> Tool -> Service -> Repository -> PostgreSQL`。LLM 理解意图和抽取实体；Graph 控制流程；Service 决定退款政策与权限；数据库是业务事实源；高风险操作由人工最终决定。

新增订单、退款、工单和审批工作台，避免只在聊天文本中“模拟”业务结果。前端的 `/enterprise/approvals`、`/enterprise/tickets`、`/enterprise/traces` 分别用于操作、审核和追踪。

## 关键模块与代码路径

| 能力 | 代码路径 |
| --- | --- |
| 企业 Graph、领域节点与状态 | `backend/package/yuxi/agents/buildin/enterprise_service/` |
| 企业 Tool 与只读知识工具 | `backend/package/yuxi/agents/toolkits/enterprise/` |
| 业务规则、审批恢复、权限与错误 | `backend/package/yuxi/services/enterprise_*.py` |
| 租户范围数据访问 | `backend/package/yuxi/repositories/enterprise_repository.py` |
| 业务 Trace | `backend/package/yuxi/services/enterprise_trace_service.py`、`enterprise_trace_repository.py` |
| 评测数据与 Runner | `backend/eval/enterprise/`、`backend/package/yuxi/evaluation/enterprise/` |
| 企业 API 与页面 | `backend/server/routers/enterprise_router.py`、`web/src/views/ApprovalView.vue`、`TicketView.vue`、`EnterpriseTraceView.vue` |

## 数据库与 API 变化

`backend/package/yuxi/storage/postgres/models_business.py` 增加 Customer、Product、Order、OrderItem、Refund、Ticket、ApprovalTask、AgentRun、EnterpriseTraceEvent 等业务表及唯一约束。租户通过部门 ID 绑定，查询和写入由 Repository 带入租户条件。现阶段仍使用项目现有建表/补表机制，尚无完整 Alembic 升级与回滚链。

P2-1 迁移体系暂缓：当前启动流程使用 `create_business_tables()` 的 `metadata.create_all`，再由 `ensure_business_schema()` 对企业表和大量上游表执行补列/建索引 SQL。直接叠加 Alembic 会产生双重 schema 所有权；已有实例还可能存在未登记的历史字段、数据或重复退款记录。因此本轮不对现有数据库执行未经验证的 `upgrade/downgrade`。后续应先盘点线上 schema 与数据、明确上游表和 Enterprise 表的所有权、为存量库建立可校验 baseline，再分别验证空库升级、存量库升级、回滚与重放；不能用 `create_all` 成功替代迁移验收。

`/api/enterprise` 增加客户、商品、订单、退款、工单、审批与 Trace 接口；审批 review 返回决策及原线程恢复状态。Agent Run 和聊天路由沿用原有 `/api/chat` 能力。所有企业业务 API 从当前认证用户取得租户和角色，不接受客户端自报租户作为授权依据。

运行探针分为 `/api/system/health`（仅进程存活）与 `/api/system/ready`（PostgreSQL、Redis 有界连通性）。Compose 和前端使用后者，数据库初始化失败会中止 API 启动；就绪探针不涵盖 MinIO、模型供应商等外部依赖。

## Agent Workflow 与 HITL

企业 Graph 显式执行意图分类、实体抽取、Knowledge/Order/Refund/Ticket 领域节点、Quality Gate 和最终答复；质量不通过最多修复一次。仅 Knowledge 节点内部创建只读 Agent；Order/Refund/Ticket/Quality 是固定 Workflow 节点，并非独立 SubAgent，原未接入 Runtime 的子 Agent 配置已移除。退款与工单调用受权限和确定性 Service 规则约束。检索文本被当作不可信数据，Grounding 在模型质量判断前核对订单、退款状态和政策来源。

低风险退款可自动落库；高风险退款创建持久化 ApprovalTask 并 interrupt。管理员批准或拒绝后，`enterprise_approval_runtime.py` 按记录中的线程与 Agent 配置恢复 checkpoint。审批落库与恢复结果分别核验，不能把“已审批”误报成“已恢复”。

关联线程的审核同时写入独立 `ApprovalResume` 状态（pending/success/failed、尝试次数、错误、恢复时间）；API 同步尝试恢复，失败后由 ARQ 延迟任务和周期扫描重试。每次重试锁定对应的恢复状态行，并先检查 checkpoint 是否已完成，避免“Graph 已恢复但状态未提交”时再次执行。最多尝试 5 次，耗尽后保留可见失败状态供人工排查；业务审批结果不会因恢复失败而回滚。

## 幂等、权限与观测

企业动作矩阵区分 `user`、`admin`、`superadmin`，在 API、Service 与 Tool 层复用。Refund、Ticket、ApprovalTask 通过业务幂等键、数据库唯一约束与 savepoint 处理重复请求和并发冲突。错误响应使用稳定的 `code/type/message/retryable`；只有明确可重试错误做有限退避。

这三个角色均指内部客服/运营账号：`user` 为普通客服，`admin` 为客服主管/租户管理员，`superadmin` 为平台管理员。被服务消费者 `Customer` 不是登录 `User`，目前没有账号与客户档案的归属绑定。订单访问按内部账号部门隔离，不是消费者本人订单隔离；企业业务接口中的 `superadmin` 仍按部门查询。

Enterprise Trace 将输入摘要、意图、节点、Tool、风险、业务对象、审批恢复、Quality Gate 与最终状态关联到租户和线程；入库前脱敏，不保存完整提示词或工具输出。Langfuse 模型追踪与企业业务 Trace 职责不同，后者可在会话运行面板和追踪工作台查看。

## Evaluation 实测与边界

`customer_service_v1.jsonl` 含 50 条独立案例，Runner 执行真实 Graph、创建一次性业务夹具并输出逐例 JSON/Markdown。历史基线：2026-10-03 未绑定知识库时 36/50，通过演示政策库后 39/50；当时产品题的 PASS 只是安全弃答，非有据回答。两次运行与当前版本的规则、知识和部分逐例期望不同，不能解释为严格同条件的增益。

2026-10-11 在本地 Docker、已索引并绑定的演示知识库、`siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash` 上完成一次当前版 50 条真实 Graph 全量评测，逐例 Markdown/JSON 位于仓库的 `backend/eval/enterprise/reports/full_verified_2026-10-11/`。**50/50 通过**，意图准确率、Tool precision/recall、审批准确率均为 1，禁用 Tool 违规率 0，P50/P95 为 7603.78/26151.56 ms，prompt/completion tokens 为 86576/17275。四条产品题均给出具体演示规格及来源，未知规格仍拒绝编造。Tool 执行成功率 0.9178，失败调用对应部分退款、缺失对象和跨租户订单等预期业务拒绝；不能把它们当作越权成功，也不能隐去这个指标。

分类请求画像显示产品题平均 6 次 LLM、1.5 次 RAG，政策题平均 6 次 LLM、1.5 次 RAG，政策 P95 38265.38 ms；订单/物流和常规退款多数为 2 至 3 次 LLM，无 RAG。确定性质量检查减少了部分路径的模型调用，但知识问答仍有重复检索与模型长尾。本轮单次 P95 与历史运行的环境/数据配置不同，不能据此宣称稳定加速或容量上限。50/50 也只是 Demo 数据集单次成绩，不是生产准确率或稳定 100%；Faithfulness、答案完整度与成本因缺少独立评判器或未核对价格仍为 N/A。

评测判定将结构化 Tool `ok=false` 记为失败，已完成案例必须通过 Quality Gate；产品案例另有必需事实文本约束，避免安全弃答虚高。知识库按真实用户 ID 鉴权，空可见列表不退回全局检索器。真实模型冒烟与离线 Graph 冒烟均可运行，但完整 50 条结果是主要效果证据。

## 测试与验证

- 2026-10-03 在运行中的 Docker API 容器再次执行 `pytest -q --tb=short`：**437 passed、5 skipped，退出码 0**。此前分组回归为单元与集成 **418 passed、5 skipped**、E2E **9 passed**；新增知识库权限、无证据 Grounding 和评测判定定向测试 **47 passed**。
- 早期 E2E 在汇总后不退出，线程栈确认是测试读取 Agent 图状态后遗留的 `aiosqlite` 工作线程。Agent 与测试夹具现已显式关闭 SQLite checkpoint 连接，API/worker 停机也统一回收；知识库更新不再替换持有连接的 Agent 实例。此前 `/api/system/tools` 在首次访问时因企业工具注入参数生成 JSON Schema 失败，且会留下半成品缓存；现改用 `tool_call_schema` 并原子发布缓存，冷启动接口和全量回归均通过。
- 定向回归：CORS、默认账号种子、Redis Run 事件测试 **9 passed**。运行中 API 的 CORS 预检实测：本地来源 200，未知来源 400。
- 后端改动文件 `ruff check` 通过；前端 `pnpm exec eslint . --cache` 与 `pnpm run build` 通过。生产构建仍提示部分异步块超过 500 kB，不等同于构建失败。
- 外部模型连通性测试 3 项默认跳过，需要明确启用。VitePress 文档站构建通过，已有文档的 `env` 代码块语法高亮提示不影响构建。
- 就绪探针运行中返回 PostgreSQL/Redis 均可用，Compose 显示 API `healthy`，浏览器首页正常且无控制台错误。

## Demo 步骤

按 [六场景 Demo 指南](./demo-guide.md) 启动 Compose、运行企业数据种子，然后验证政策问答、物流查询、低额退款、高额批准、高额拒绝、知识库注入隔离。政策问答和注入隔离需要实际可检索的知识库；高额审批恢复必须使用新建且绑定 Agent 线程的订单，不能用仅供列表展示的种子审批任务替代。

## 已知限制与下一步

消费者自助门户尚未实现；若开放给消费者，需要新增独立认证、`User -> Customer` 绑定及订单所有权校验，不能复用当前内部员工的部门级订单权限。

1. 知识库图片仍可能位于公开可读的 MinIO bucket；上线前需改私有访问、迁移旧对象并复测多租户隔离。
2. Docker Compose 默认演示账号和示例密码仅限本地。种子服务已停止在新日志中输出密码；历史日志与示例凭证仍须清理或轮换。CORS 默认仅开放本地来源，跨域部署需设置 `YUXI_CORS_ORIGINS`。
3. 缺少完整数据库迁移/回滚链、生产容量与稳定性测试；此前 Docker 环境曾发生数据库重启，仍需故障演练。
4. 演示知识库包含 10 个模拟产品、退款/换货/物流/质保/售后资料，仅授权默认部门；全量评测中产品和政策题均从真实检索结果回答。当前 Demo 仅接受整单退款，部分金额返回 `PARTIAL_REFUND_NOT_SUPPORTED`；历史部分退款记录不会自动迁移。在线恶意知识文本注入仍需在隔离知识库演示验证，不能用普通 Prompt Injection 案例代替。
5. 下一阶段可建设企业管理驾驶舱与告警基线，补独立 Faithfulness/答案完整度评判、价格核对、审计保留策略、私有对象存储及部署演练。上述能力未完成前，不应宣称生产就绪。

## 简历表述边界

可写本人二次开发的企业领域模型、确定性退款流程、LangGraph 企业 Agent Workflow（含只读 Knowledge Agent）、人工审批恢复、租户权限、幂等、评测框架与脱敏 Trace，并在面试中展示代码和测试。不可把上游 Yuxi 的通用平台、RAG/MCP/Sandbox 基础、社区数据说成从零独立完成；不可把固定业务节点包装成多个独立 SubAgent，也不可写未经实测的准确率、成本下降或生产并发性能。
