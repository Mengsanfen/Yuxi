# 企业 Agent Evaluation

数据集位于 `backend/eval/enterprise/datasets/customer_service_v1.jsonl`，包含 50 条案例，覆盖意图、订单、退款、审批、投诉、越权和注入等。Runner 为每条案例创建一次性业务夹具，执行真实 Enterprise Graph，并生成 JSON 和 Markdown 报告。入口：`backend/package/yuxi/evaluation/enterprise/runner.py`。

```bash
docker exec api-dev uv run --group test python -m yuxi.evaluation.enterprise.runner --limit 3
# 完整评测：去掉 --limit；可用 --model、--user-id、--output 指定环境与输出
# 已入库并授权的政策知识库可用 --knowledge-base "名称" 临时启用，不修改 Agent 持久配置
```

指标由 `metrics.py` 确定性计算，包括 case pass rate、intent accuracy、Tool selection precision/recall、禁用 Tool 违规率、审批/升级匹配、任务完成率、延迟与 Token。precision = 正确选择的 Tool 数 / 实际选择的 Tool 数；recall = 正确选择的 Tool 数 / 期望 Tool 数。没有真实模型运行报告时，不能把数据集数量或单元测试通过率写成 Agent 效果指标。

P1-1 将运行时分类拆为 `domain/action/ticket_type/risk_level/security_signals`，同时保留由新字段派生的旧 `intent` 供现有指标和报告使用。普通工单创建不再标成投诉；四条工单创建案例增加对象、动作与工单类型期望。报告中的 `domain_accuracy`、`action_accuracy` 仅对显式标注这些字段的案例计算，不代表整个数据集的对象/动作准确率。历史分数不能证明新分类器更准确；需要在同一模型、知识库和案例条件下重跑并逐例核对。

Faithfulness/答案完整度缺少独立评判器时记为 N/A；没有核实价格配置时成本记为 N/A。真实评测会调用模型服务并可能产生费用。2026-10-03 的 50 条全量实测报告位于 `backend/eval/enterprise/reports/full_2026-10-03/enterprise_eval_20261003T020804Z.md`，36/50 通过；该次运行时企业 Agent 尚未绑定知识库，产品/政策案例安全失败，不可把本次结果宣传为生产准确率。已完成案例只有通过 Quality Gate 才计入 case pass，结构化 Tool 失败计入工具失败。完整结果与限制见[最终实施报告](./final-implementation-report.md)。

随后新增隔离的演示政策库并绑定默认企业 Agent；2026-10-03 的 50 条全量报告位于 `backend/eval/enterprise/reports/full_policy_bound_2026-10-03/enterprise_eval_20261003T122303Z.md`，39/50 通过。当时四条产品题被标为 PASS 的原因是安全弃答，**不是有据的产品解答**。该报告及更早的 36/50 报告均为规则、知识库和部分逐例期望变更前的历史结果，不能与当前版本作严格同条件横比。

## 当前全量与冒烟

冒烟可执行 `docker compose exec -T api python -m yuxi.evaluation.enterprise.runner --limit 5`；完整评测将 `--limit` 设为 `50`。离线 Graph 冒烟单元测试在 `backend/test/unit/evaluation/test_enterprise_graph_smoke.py`，它不替代真实模型评测。

2026-10-11 在本地 Docker、已索引并绑定的演示知识库、`siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash` 上完成一次 50 条真实 Graph 全量评测。逐例 Markdown/JSON 位于仓库的 `backend/eval/enterprise/reports/full_verified_2026-10-11/`。50/50 通过；意图准确率、Tool 选择 precision/recall、审批准确率均为 1，禁用 Tool 违规率为 0，P50/P95 为 7603.78/26151.56 ms。四条产品题均回答了资料中的具体规格并引用来源，非安全弃答。Tool 执行成功率为 0.9178，未成功调用对应部分退款、缺失或跨租户对象等预期业务拒绝，不能解读为这些安全边界失败。

这只是单次 Demo 数据集结果，不证明生产准确率、稳定 100% 或压测容量。知识与政策题仍有重复检索和较高延迟；P95 对模型供应商波动敏感。Faithfulness、答案完整度及成本仍为 N/A，详见[最终实施报告](./final-implementation-report.md)。
