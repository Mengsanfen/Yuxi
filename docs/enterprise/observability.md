# 业务 Trace 与可观测性

`EnterpriseTraceRecorder` 将输入、节点、Tool、审批恢复和最终状态写入 `enterprise_trace_events`。摘要先经 `sanitize_trace_payload` 脱敏并限制长度，不保存完整提示词、回答或 Tool 输出。查询通过 `GET /api/enterprise/traces`、`GET /api/enterprise/traces/{trace_id}` 和线程最新 Trace API，均按当前用户的租户过滤。

前端 `web/src/views/EnterpriseTraceView.vue` 提供独立工作台，`web/src/components/enterprise/` 提供会话内运行面板。展示意图、节点、Tool、风险、审批、Quality、最终状态、耗时和可得的 Token 信息。具体事件模型在 `backend/package/yuxi/storage/postgres/models_business.py`，组装逻辑在 `enterprise_trace_service.py`。

新产生的 Tool/检索事件在调用边界使用 `perf_counter` 测量，并以 `timing_source=measured` 标识；详情页只汇总这些实测值。历史事件或没有计时信息的工具调用保持 `null`，不再用节点耗时均分来冒充工具耗时。Graph 节点和整轮请求耗时仍是不同口径，不能相加解读为模型耗时。

Trace 中只有 `knowledge` 节点运行独立 Knowledge Agent；其他节点归属 `EnterpriseServiceAgent`。历史事件中曾用 `order-agent` 等名称标记业务节点，界面仍能读取旧记录，但将其显示为节点而非独立智能体。

Langfuse 偏向模型与调用链观测；业务 Trace 对齐退款、审批、工单和租户权限。事件写入是辅助通道，写入失败会记录警告，不应覆盖已提交的业务事实。当前没有企业告警基线或经验证的成本报表。
