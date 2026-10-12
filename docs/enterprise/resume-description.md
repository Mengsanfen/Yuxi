# 简历描述

## 项目一句话

基于开源 Yuxi 与 LangGraph 二次开发企业级 Agent 客服工作流，打通知识问答、订单物流、退款决策、人工审批与售后工单流程。

## 精简版项目经历

**NexaMind Enterprise｜企业客服与售后自动化平台**
技术栈：Python、FastAPI、LangGraph、Vue 3、PostgreSQL、Redis、Docker Compose

- 设计显式 LangGraph 售后 Workflow，按结构化意图路由知识、订单、退款与工单节点；仅知识节点运行只读 Agent，将事实校验和 Quality Gate 固定在业务路径中。
- 实现企业领域 Service/Repository 与 Tool，覆盖确定性退款规则、工单状态机、部门级租户隔离和角色权限校验；通过唯一约束与 savepoint 防止并发重复写入。
- 实现高风险退款 `ApprovalTask + interrupt/resume`，管理员审核后恢复原线程；提供审批、工单和运行追踪页面。
- 建立 50 条企业 Agent 评测数据集与 JSON/Markdown 报告流程，补充业务 Trace 脱敏、知识检索只读隔离与提示词注入测试。

## 边界与数字

上游 Yuxi 已提供通用 LangGraph 平台、知识库/知识图谱、MCP、Skills、沙盒及前后端基础；上述条目描述的是企业场景二次开发。项目展示与面试时应保留上游归属。50 条是数据集规模，不是模型准确率；只有实际执行完整评测并留存报告后，才能写通过率、耗时或成本指标。不要宣称生产上线、高并发压测或完全阻断所有注入。
