# 人工审批与原线程恢复

高风险退款由 `EnterpriseService.request_refund()` 创建 `Refund(status=pending_approval)` 与 `ApprovalTask(status=pending)`。工作流调用 `interrupt()` 暂停，LangGraph checkpoint 保留线程状态。审批任务保存 `thread_id`、`agent_id`、`agent_config_id` 与申请人信息。

管理员在 `/enterprise/approvals` 审核。后端 `POST /api/enterprise/approvals/{task_id}/review` 在事务内先锁定审批任务行，再检查待审状态并更新审批、退款和订单；并发审核只有一个请求能提交，其他请求返回 `APPROVAL_ALREADY_REVIEWED`（HTTP 409）。批准时订单变为 refunded，拒绝时订单保持原状态。提交后仅成功请求调用 `resume_reviewed_approval()`，用原 `thread_id` 和申请人身份恢复 Quality Gate 与最终回复。调用成功与审批入库是两个阶段：若恢复失败，API 的 `resume` 字段会报告失败，不能声称整个流程已成功。独立 `ApprovalResume` 记录恢复状态与尝试次数，ARQ 延迟任务和周期扫描重试；重试先检查 checkpoint，最多尝试 5 次，耗尽后保留失败状态供排查。

演示时应新建待审退款。种子里的待审任务没有绑定 Agent 线程，适合展示审批列表，但审批它们不会演示原线程恢复。对应代码：`backend/package/yuxi/services/enterprise_approval_runtime.py`、`backend/server/routers/enterprise_router.py`；回归：`backend/test/integration/api/test_enterprise_approval_concurrency.py`、`backend/test/e2e/test_enterprise_refund_workflow_e2e.py` 和 `test_enterprise_agent_workflow_e2e.py`。
