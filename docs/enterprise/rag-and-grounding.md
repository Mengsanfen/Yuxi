# RAG 与 Grounding

企业知识问答复用 Yuxi 的知识库检索能力。Knowledge Agent 的 Tool 白名单只包含 `list_kbs` 和 `query_kb`，没有退款、审批或工单写 Tool；实现见 `backend/package/yuxi/agents/buildin/enterprise_service/security.py`。

检索内容一律视为不可信数据。安全检查识别覆盖指令、提权和要求执行写操作的文本；命中时隔离原文，主 Graph state 仅接收脱敏的来源、数量和安全信号。这里的规则匹配是防护的一层，不能保证识别所有变体。

Grounding 检查以订单 Tool 返回的状态、退款/审批结果和检索来源为依据。典型拦截：订单仍为 `shipped` 却声称已签收；退款仍在 `pending_approval` 却声称成功；引用不存在的政策。确定性检查在模型 Quality Gate 前执行。代码在 `security.py` 和 `nodes.py`；测试在 `backend/test/unit/agents/test_enterprise_workflow.py`。

本地演示可运行 `docker compose exec -T api python scripts/seed_enterprise_policy_kb.py --bind-agent`，幂等索引模拟政策、产品与售后资料并绑定默认企业 Agent；仅有企业订单种子数据不会自动生成知识库。模拟资料不能作为真实商家承诺。
