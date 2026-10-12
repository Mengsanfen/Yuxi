# Enterprise Agent Evaluation

企业评测与现有知识库 RAG Evaluation 相互独立。Runner 使用真实
`EnterpriseServiceAgent` LangGraph，程序化评估意图、工具、业务状态、审批和安全边界。

## 运行

项目以 Docker Compose 为开发事实来源：

```bash
docker exec api-dev python -m yuxi.evaluation.enterprise.runner \
  --dataset /app/eval/enterprise/datasets/customer_service_v1.jsonl \
  --limit 50
```

按案例、模型或输出位置运行：

```bash
docker exec api-dev python -m yuxi.evaluation.enterprise.runner \
  --case-id refund-low-001 \
  --case-id refund-high-001 \
  --model siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash \
  --output /app/eval/enterprise/reports/latest.json
```

`--case-id` 可以重复或使用逗号分隔。Runner 为每个需要业务数据的案例创建一次性租户内夹具，
运行后清理客户、商品、订单、退款、审批和工单，不修改演示数据。

## 数据集

`customer_service_v1.jsonl` 包含 50 条案例，覆盖知识问答、订单物流、低额/高额退款、投诉工单、
信息缺失、不存在订单、重复请求、跨租户、越权和 Prompt Injection。

每条案例声明预期意图、允许/禁止工具、审批与升级预期、最终状态和必要文本约束。`fixture` 中的
`{{order_no}}`、`{{customer_id}}`、`{{ticket_id}}` 会在运行时替换为一次性业务数据。

## 指标

确定性指标包括 Intent Accuracy、Tool Selection Precision/Recall、Forbidden Tool Violation Rate、
Tool Execution Success Rate、Task Completion Rate、Approval Accuracy、Escalation Accuracy、
Quality Gate Pass Rate、P50/P95 Latency 和 Token Usage。

Runner 同时输出 JSON 与 Markdown。未配置可信模型价格时 Estimated Cost 为 `N/A`；未显式配置
LLM Judge 时 Faithfulness 和 Answer Completeness 为 `N/A`，不会用假数据填充。

## 实测报告

2026-10-11 在本地 Docker、已索引的演示知识库及 `siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash`
环境下执行完整 50 例，结果为 50/50 通过、禁用 Tool 违规率 0、审批准确率 1，
P50/P95 为 7603.78/26151.56 ms。四条产品题均命中具体演示规格和引用。
逐例证据见 [Markdown](reports/full_verified_2026-10-11/enterprise_eval_20261011T072956Z.md)
和 [JSON](reports/full_verified_2026-10-11/enterprise_eval_20261011T072956Z.json)。
这是单次、使用模拟资料的运行，不能据此宣称生产表现或稳定 100%。
Tool Execution Success Rate 为 0.9178，因部分退款、缺失/跨租户对象等预期业务拒绝也计为失败调用。
