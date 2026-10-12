# 面试问答

以下回答对应当前实现，不代表平台所有能力均由企业二开从零构建。

1. **项目真的是五个 SubAgent 协作吗？** 不是。主流程是 `EnterpriseServiceAgent` 的固定 LangGraph Workflow；订单、退款、工单和质量检查都是节点。只有 Knowledge 节点内部创建独立只读 Agent。
2. **为什么不让 Supervisor 自由规划退款？** 当前运行时没有企业 Supervisor 自由委派。模型可能误选 Tool 或受检索文本影响；固定流程先经 `refund_order` 验证，再由 `enterprise_refund_workflow.py` 和 Service 执行规则。
3. **为什么用显式 LangGraph Workflow？** 条件边能证明退款一定经过订单验证和 Quality Gate；`test_enterprise_workflow.py` 对这些边有断言。
4. **LLM、Graph、Tool、Service、Repository 各做什么？** LLM 理解与表述，Graph 控制流程，Tool 暴露能力，Service 执行业务规则，Repository 做带租户条件的持久化。
5. **为什么退款规则不写在 Prompt？** 金额、期限和状态需要确定性判定；`RefundPolicyService.evaluate()` 可独立测试，也不会随模型措辞变化。
6. **重复 Tool Call 如何不重复退款？** Service 按 tenant 和幂等键先查；Repository 的唯一约束与 savepoint 处理并发冲突并返回已存在对象。
7. **高风险退款怎样 interrupt/resume？** 申请创建 `ApprovalTask`，Graph 暂停；管理员审核后 `resume_reviewed_approval()` 用原 thread 与申请人身份恢复。
8. **为什么能恢复原线程？** 任务保存 `thread_id`、`agent_id`、`agent_config_id`，LangGraph checkpoint 保留执行位置；缺少关联字段时只返回 `not_linked`。
9. **多租户如何隔离？** tenant 来自认证用户部门或运行时上下文，Repository 查询附 `tenant_id`；API 和 Trace 查询同样过滤。
10. **三个角色有什么差异？** 登录 `User` 均为内部人员，`Customer` 只是被服务消费者档案，二者没有账号归属关系。`user` 是普通客服，可在本部门读订单、申请退款、创建工单；`admin` 是客服主管/租户管理员，`superadmin` 是平台管理员，二者在企业接口还可审批、更新/关闭工单、维护客户商品，但仍受部门数据范围约束。消费者自助门户尚未实现。
11. **如何防 Prompt Injection？** Knowledge Agent 只有只读 Tool；检索文本被视为不可信并扫描指令性内容，主状态只留脱敏摘要。规则匹配仍有漏检风险。
12. **Knowledge Agent 为什么没有退款 Tool？** 政策文本可被污染，检索路径不应有业务写入权限；退款只能进入显式退款分支。
13. **Quality Gate 为什么强制？** 业务分支都连到 `quality`；先做确定性事实比对，再做模型检查。失败最多修复一次，最终不能虚构成功。
14. **Evaluation 如何设计？** 50 条 JSONL 案例定义预期意图、Tool、审批和结果；Runner 建一次性夹具跑真实 Graph，输出逐例与汇总报告。
15. **Tool Selection Accuracy 怎么算？** 当前实现报告 precision/recall：期望与实际 Tool 集合的交集分别除以实际数和期望数；不能把它与单一 accuracy 混为一谈。
16. **Trace 怎么记录？** `EnterpriseTraceRecorder` 接收 Graph update，生成输入、节点、Tool、resume、result 事件，入库前脱敏。
17. **已有 Langfuse 为什么还要业务 Trace？** Langfuse 面向模型调用；业务 Trace 需要订单、审批、风险、租户和最终状态的可查询关系。
18. **RAG、GraphRAG、MCP、Skills 的关系？** RAG/GraphRAG 提供知识来源，MCP 接外部工具，Skills 是运行指导；企业退款使用受控领域 Tool 而非任意 MCP 写操作。
19. **为什么没引入 Kafka 等组件？** 现有 Postgres、Redis/ARQ、LangGraph 已覆盖当前规模的持久化、异步和流程需求；新增基础设施会增加部署和故障面。
20. **最难的工程问题？** 高风险退款审批与原线程恢复的一致性，以及重复请求/并发写入不会双退款。用持久化审批关联、唯一约束、savepoint 和 E2E 验证。

回答效果指标前先展示 `evaluation.md` 中真实运行的报告；目前不能引用未经运行的准确率或成本收益。
