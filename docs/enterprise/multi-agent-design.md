# 企业 Agent Workflow 职责

企业场景按知识、订单、退款、工单和质量划分 LangGraph 节点职责，而非五个独立 SubAgent。`EnterpriseServiceAgent.get_graph()` 编译 `graph.py` 中的固定 `StateGraph`；`_build_enterprise_subagents()` 原先只构造配置，从未接入 Runtime，现已移除。`order_node`、`refund_node`、`ticket_node` 直接调用受权限约束的 Service/Repository；`quality_node` 执行确定性检查和模型质量判断。只有 `knowledge_node` 内部通过 `create_agent()` 创建真正的只读 Knowledge Agent，工具限于 `list_kbs`、`query_kb`。

不存在负责自由委派业务任务的 Supervisor。显式 Graph 固定意图分支、退款前的订单验证、Quality Gate 和最多一次修复；通用 SubAgent 配置不会改变这条企业流程。这样可以分别测试模型理解、流程路由和确定性业务规则。

| 组件 | 决策范围 |
| --- | --- |
| LLM | 语义分类、实体提取、回答措辞 |
| LangGraph | 固定节点次序、条件路由、checkpoint 与恢复 |
| Knowledge Agent / 业务节点 | 前者只读检索；后者通过 Service 执行受控业务操作 |
| Service/Repository | 权限、业务规则、租户隔离、幂等与事实读写 |
| 人工审批 | 高风险退款的最终决定 |

通用 Yuxi 的 MCP、Skills 和沙盒仍可用于其他 Agent；它们不是企业退款路径的授权替代品。
