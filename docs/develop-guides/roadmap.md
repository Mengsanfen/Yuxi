# 开发路线图

路线图可能会经常变更，如果有强烈的建议，可以在 [issue](https://github.com/xerrors/Yuxi/issues) 中提。

日志添加规范（For Agent）:

- 同一版本的多次功能更新时，应以功能为单位进行更新，比如之前添加了 A 功能的更新，在后续的更新中修复了因 A 功能引入的 bug，那么这个修复说明应该和 A 功能描述放在一起，而不是新增一条修复记录，功能更新同理。


### 看板

- 企业客服 V1 业务闭环：已完成领域模型、部门级租户隔离、确定性退款规则、工单状态机、幂等 Demo 数据、业务 API；企业 Agent 已升级为显式 LangGraph Workflow，由固定条件边控制意图分类、实体提取、订单验证、退款/审批、工单、强制 Quality Gate 和单次修复。API、Service 与 Agent Tool 已共享 `superadmin/admin/user` 企业动作权限矩阵，并统一 `code/type/message/retryable` 错误契约；Refund、Ticket、ApprovalTask 通过唯一约束与 savepoint 支持并发幂等 replay。真实自然语言 E2E 已覆盖低额自动退款、重复请求、高额审批通过和拒绝，并验证原线程 interrupt/resume 与最终回复。企业 Agent Evaluation 已提供 50 条独立数据集、一次性业务夹具、真实 Graph Runner、确定性指标以及 JSON/Markdown 报告；Enterprise Trace 已串联输入、意图、节点、工具、业务结果、风险、审批恢复、质量门与最终状态，并提供租户隔离 API、脱敏摘要、独立追踪工作台和会话内运行面板。Knowledge Agent 已收敛为只读工具白名单，检索内容按不可信数据处理，并通过提示词注入隔离、确定性 Grounding 检查和 Trace 安全摘要阻断知识库中的越权指令。下一步建设企业管理驾驶舱与告警基线。
- Langfuse 增加 self-host 模式支持，补齐私有化部署与配置说明（已支持 cloud，待调试）
- 检索测试中，添加问答
- 集成 Memory，基于 deepagents 的文件后端实现，需要考虑定位
- Yuxi-cli 相关的功能，放在后续版本中实现（不是类似于编程助手，而是管理平台的工，等各个 router 接口优化之后）
- 完善个人知识库（仅设想，欢迎讨论）
- 完善测试基准自动生成功能，目前的实现过于简单，无法覆盖实际需求
- 完善 Skills 的环境变量注入
- 拓宽检索的知识源，统一多知识源（channel），目前已知知识库/知识图谱/网页，可拓展：个人知识库、数据库、历史对话等
    - 前置任务，多知识库并行检索（扩展 query_kb）

### Bugs
- 目前的知识库的图片存在公开访问风险
- 生成基准测试会把所有的向量都计算一遍不合理

### BREAKING CHANGE（不兼容变更，0.7 版本再实现）
- 将自定义provider 的实现逻辑，从文件移动到数据库中，并将相关处理代码，移出 config 文件，放到 provider 模块中
- 已补充方案文档：`docs/vibe/2026-04-18-custom-provider-db-refactor-plan.md`，明确采用“provider 一行、models 放 JSON、移除 provider 默认模型”的落地方案
- 优化知识库的 API 接口设计，使用 /{db_id}/xxx 的形式，整合 mindmap / eval 接口



## 版本记录

### 0.6.2 开发记录

<!-- 0.6.2 的内容请放在这里 -->
- 企业退款 P0-1 收口：当前 Demo 仅支持退款金额等于订单实付金额的整单退款；部分金额请求返回 `PARTIAL_REFUND_NOT_SUPPORTED`，不写入退款或更新订单状态。补充 Service、Tool、HTTP 和真实 Agent 回归，更新演示政策知识库、种子及 50 条评测数据的退款用例。旧 Eval 分数为规则变更前历史结果，历史部分退款记录不自动迁移。
- 企业退款 P0-2 并发保护：在退款表增加同租户同订单、非 `REJECTED` 状态的部分唯一索引；不同幂等键竞争时仓储层回查同一有效退款，避免第二笔退款及重复审批。API 并发回归核验 5 个不同 key 只对应 1 笔有效退款和 1 张审批任务，并覆盖拒绝后重新申请。已有异常重复数据需在补建索引前人工审计，不自动清理。
- 企业审批 P0-3 并发保护：审核同一 `ApprovalTask` 前执行租户限定的 `SELECT FOR UPDATE`，在事务内检查待审状态并更新审批、退款及订单，提交后仅成功请求尝试恢复原线程。真实 API 并发回归覆盖批准/拒绝竞争和相同决策重复提交，要求一个成功、其余返回 `APPROVAL_ALREADY_REVIEWED`（409），业务状态与获胜决策一致。
- 企业身份 P0-4 语义收口：明确登录 `User` 是内部客服/运营账号，`Customer` 是被服务消费者档案；`user/admin/superadmin` 分别为普通客服、客服主管/租户管理员、平台管理员。现有企业订单权限按部门租户隔离，没有 `User -> Customer` 所有权校验；消费者自助门户列为未来工作。同步修订 README、架构、安全、权限、面试与实施报告，不改变数据库/API。
- 企业 Agent P0-5 表述收口：确认 `_build_enterprise_subagents()` 从未接入 Runtime，移除未使用的子 Agent 配置和 Prompt；主流程为固定 LangGraph 业务节点，仅 Knowledge 节点内部创建只读 Agent。Trace 新事件按真实执行者归属，历史伪 Agent 名称在界面按节点展示；README、架构、简历和面试文档统一使用企业 Agent Workflow 表述。
- 企业意图 P1-1 分类收口：分类结果拆为业务对象 `domain`、动作 `action`、工单类型 `ticket_type`、风险和安全信号，Graph 按对象与动作路由；保留派生的旧 `intent` 兼容 Eval、Trace 和前端，旧 checkpoint 仍可按原字段路由。普通售后工单创建与投诉创建分离，后者保持高风险和高优先级；Eval 修正两条普通建单的旧投诉标签，并对四条建单案例单独核对对象、动作和类型。注入文本安全拒绝逻辑暂不改变，历史 Eval 分数不作为本轮效果指标。
- 企业 Agent P1-2/P1-3：将业务意图与 `instruction_override` 安全信号分离；有订单标识的恶意退款请求仍识别退款域，但退款节点在写入前拒绝绕过规则的指令。演示知识库幂等索引 10 个产品及退款、换货、物流、质保和售后 FAQ，补齐四条评测产品题所问的演示规格；未收录规格继续拒绝编造。登录账号 ID 与运行线程 ID 分开传入知识库鉴权。
- 企业 Agent P1-4/P1-5：按逐例失败原因修正明确的分类/缺参期望，保留 50 条真实 Graph 全量评测和分类请求画像；低风险自动退款及已验证订单查询使用确定性质量检查，高风险与知识问答仍保留模型质量门。模型波动与 RAG 多次检索仍会造成长尾，不能把单次 P95 当作稳定容量指标。
- 企业 Trace P1-6 与 HITL P1-7：Tool/检索在真实调用边界计时，旧的无计时记录返回空值而非节点均分；审批业务提交与 Agent 恢复分别持久化。关联线程的审批恢复失败后由 ARQ 延迟任务及周期扫描重试，按恢复状态行串行化并检查 checkpoint，最多 5 次，耗尽后保留可见错误供人工处理。
- 企业收口 P2：新增 PR 的 Ruff、企业单元/集成、前端 lint/build 和离线 Graph Eval smoke，真实模型 Eval 由手动工作流执行；提供只读订单、审批与 Trace API 小规模压测脚本。Alembic 暂缓：当前 `create_all` 与大量启动补列 SQL 共管 schema，须先做存量数据/结构盘点与 baseline、空库及存量升级/回滚验收，避免破坏现有启动链。
- 企业评测最终复测（2026-10-11）：在本地 Docker、已绑定演示知识库和 `DeepSeek-V4-Flash` 上完成当前版 50 条真实 Graph 全量运行，50/50 通过，禁用 Tool 违规率 0，审批准确率 1，P50/P95 为 7603.78/26151.56 ms；四条产品题均有具体演示规格与引用。报告保存在 `backend/eval/enterprise/reports/full_verified_2026-10-11/`。这是单次模拟数据集结果，不是生产准确率或稳定性能承诺；在线恶意知识文本注入 Demo、独立评判器、对象存储私有化和数据库迁移链仍未完成。
- 新增企业智能客服 V1：基于现有 Agent Runtime 增加结构化意图、实体提取与 Knowledge、Order、Refund、Ticket、Quality 领域节点；关键业务由显式 `StateGraph` 和条件边控制，订单/退款/工单结果必须经过 Quality Gate，失败最多修复一次。企业 Tool 统一通过 Service/Repository 访问租户数据，高风险退款会持久化 `ApprovalTask` 并暂停 LangGraph，管理员在审批中心处理后由受控服务恢复原线程。补充 `EnterpriseRuntimeIdentity` 和企业动作权限矩阵，普通用户仅可查询订单、申请退款与创建工单，工单更新/关闭、退款审批及客户产品维护仅限管理员，并在 API、Service、Tool 三层保持一致；统一企业异常层级和 Tool/API 安全错误载荷，仅对显式可重试错误执行最多两次退避，并通过数据库 savepoint 将并发 Refund、Ticket、ApprovalTask 冲突转为同对象 replay。真实自然语言 Agent E2E 已覆盖低额自动退款及重复请求、高额审批通过/拒绝和原线程恢复，并修复退款后订单证据快照未刷新导致 Quality Gate 误判的问题；Redis SSE 事件写入作为辅助通道降级处理，短暂持久化故障不再覆盖 PostgreSQL 中的真实 run 结果。前端新增审批中心与售后工单工作台。
- 新增 Enterprise Trace 与 Observability：增加租户级 `enterprise_trace_events` 事件模型，将 LangGraph `updates` 节点流、工具调用、业务对象、风险、审批恢复、质量门和最终状态串成可查询 Trace；事件入库前统一脱敏并限制摘要大小，不持久化完整提示词、回答或工具输出。新增 Trace 列表、详情和线程最新 Trace API，前端提供独立运行追踪工作台与企业会话运行面板，展示节点/智能体、耗时、Token、订单/退款/审批状态和最近工具调用。
- 增加企业知识安全与 Grounding 防护：Knowledge Agent 仅保留 `list_kbs`、`query_kb` 两个只读工具，将检索结果标记为不可信数据；命中提示词覆盖、提权或业务写入指令时隔离原文并直接生成安全答复。Quality Gate 在调用模型前确定性校验订单状态、退款审批状态与政策来源，Trace 和会话运行面板仅展示脱敏后的隔离信号。新增本地演示政策库幂等种子，仅对默认部门可见，支持显式绑定默认企业 Agent；Grounding 可从实际检索到的 Markdown 一级标题验证政策名称引用。在线知识库注入 Demo 仍待完成；新配置全量 Eval 结果见上方复测记录。
- 补齐企业场景 README 与 `docs/enterprise/` 架构、Workflow、HITL、权限、评测、追踪、Demo 和面试说明，并在最终实施报告中区分实测与未验证指标；修复测试导入污染、旧测试桩和 Redis Run 续读重复事件。CORS 默认收敛到本地开发来源，支持 `YUXI_CORS_ORIGINS` 受控配置；演示账号种子日志不再输出密码。2026-10-03 的旧评测分别为 36/50（未绑定知识库）与 39/50（仅政策资料、产品安全弃答），作为历史基线保留；产品资料、整单退款语义和失败案例已在后续任务修正，当前全量结果见上方复测记录。
- 区分存活与就绪探针：新增 `/api/system/ready` 对 PostgreSQL 和 Redis 做有界连通性检查，Compose 与前端改用就绪状态；数据库初始化失败时终止 API 启动，避免业务不可用却持续返回健康。MinIO、模型供应商及其他外部依赖仍需部署级监控与故障演练。
- 修复 Agent 与工具元数据生命周期：Agent 自有 SQLite checkpoint 连接在测试夹具及 API/worker 停机时显式关闭；知识库变更只失效已有 Agent 的 Graph 缓存，不再替换实例并遗留连接。工具列表改用排除注入参数的 `tool_call_schema`，避免企业工具的 `ToolRuntime` 触发 JSON Schema 生成异常；元数据缓存仅在完整构建后发布，防止首次请求失败后返回不完整列表。
- 完成前端质量与加载优化：修复 Dashboard 图表卸载时错误释放实例、模型配置刷新按钮未定义状态、通用信息卡不接受 Lucide 函数组件、文件详情首次打开时预览初始化顺序异常、检索配置按需挂载后首开空白以及 Skill 详情未使用变量；Dashboard 按需注册 ECharts 图表与组件，入口按实际使用范围注册 Ant Design Vue，任务中心、设置面板及知识库详情的图谱、导图、评估和弹窗改为按需加载。生产构建中 Dashboard JS 由 1188.10 kB 降至 610.80 kB，入口 JS 由 1860.09 kB 降至 1471.62 kB，知识库详情路由 JS 由 731.27 kB 降至 57.53 kB；图谱等大依赖仍作为独立按需块保留，浏览器回归与全量 ESLint 通过。
- 扩展管理界面交互逻辑重构：将 MCP / Subagents / Skills 三个标签页从「左侧边栏 + 右侧详情面板」布局重构为「卡片式网格布局 + 路由跳转二级页面」布局，工具标签页改为卡片网格布局 + 弹窗详情（保持弹窗内容不变）。新增共享组件 `ExtensionCard`、`ExtensionCardGrid`、`ExtensionToolbar`、`ExtensionDetailLayout`，详情页（`McpDetailView`、`SubagentDetailView`、`SkillDetailView`）使用居中宽度限制，路由规划为 `/extensions/mcp/:name`、`/extensions/subagent/:name`、`/extensions/skill/:slug`。
- 统一卡片样式：`ExtensionCard` 新增 `tags` prop 支持传入 `[{label, color}]` 数组，内部使用 `<a-tag bordered=false size=small>` 渲染，与知识库卡片标签风格统一；知识库列表页 `DataBaseView` 改用 `ExtensionCard` + `ExtensionCardGrid` 替代原有自定义卡片，移除冗余 card 样式。
- 调整应用主导航：`AppLayout` 从默认窄栏升级为默认展开的侧边栏，保留折叠态图标导航；侧边栏样式收敛为 14px 文本 + 18px 图标的标准紧凑密度，并统一导航项、任务中心、GitHub、用户信息的图标与文字对齐。折叠态改为仅通过显式按钮展开，避免空白区域误触发。
- 合并智能体对话导航：移除 `AgentChatComponent` 内部聊天侧边栏，将新建对话入口和对话历史移动到 `AppLayout` 主侧边栏，并通过共享线程 store 统一管理历史列表、当前线程、重命名、删除、置顶和分页加载。
- 新增独立模型配置模块：增加 `model_providers` 表、独立管理接口和”模型配置”页面，支持 provider 基础信息、可配置模型列表端点、远端候选模型、`enabled_models` 的早期配置验证；启动时会补齐内置 provider 模板，`provider_type` 暂统一默认为 `openai`，该模块暂不接入现有运行时模型选择逻辑。远端模型加载默认使用 `/models` 获取 chat/通用模型，provider 声明 `embedding` 能力时使用 `/embeddings/models` 获取 embedding 候选，rerank 模型列表端点按供应商文档显式配置后加载；修复路由请求模型未接收 `embedding_base_url`/`rerank_base_url` 导致前端已填写仍被后端校验拦截的问题。补充手动添加模型能力：`enabled_models[i]` 新增可选 `source: "manual"|"remote"` 字段（默认 `remote`），管理员可通过”+ 手动添加”入口录入远端清单未覆盖的模型（典型：自部署 embedding/rerank），手动模型在前端跳过”远端不存在”的 stale 警告并显示「手动」标签；type 选项受 `provider.capabilities` 约束，后端在 `_normalize_payload` 与 `update_provider_config` 双层一致性校验中拦截越权写入。

---

历史版本发布记录已迁移到 [版本变更记录](./changelog.md)。

维护说明：
- roadmap 仅保留未来规划（看板/Bugs/里程碑方向）。
- 具体版本发布内容统一维护在 changelog。
