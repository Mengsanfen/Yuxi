# MCP 与领域 Tools

上游 Yuxi 已有 MCP、Skills 和通用 Tool 注册机制。企业二开沿用该运行时，将订单、退款、工单操作封装在 `backend/package/yuxi/agents/toolkits/enterprise/`，其内部通过 `EnterpriseService` 与 `EnterpriseRepository` 访问数据。

企业写 Tool 的真实权限来自运行时注入的 `tenant_id`、`user_id`、`user_role`，而不是模型生成的参数。API、Service 和 Tool 共用 `EnterprisePermissionService` 的动作矩阵。知识 Agent 不持有企业写 Tool；即使检索内容要求“直接退款”，也不会因此获得调用资格。

MCP 是接入外部工具的通用协议能力，Skills 是运行指导材料，RAG/GraphRAG 是知识来源；它们与企业领域 Tool 并列接入通用平台，但退款等写操作必须经过领域 Service。当前没有为企业退款另建 MCP Server，也没有引入新 Workflow 引擎。
