# 幂等、错误与重试

退款和工单写入先查询 `(tenant_id, idempotency_key)`。Repository 对 Refund、Ticket、ApprovalTask 使用数据库唯一约束和嵌套事务 savepoint：并发写入冲突时回查已有对象并返回 replay。退款另有 `(tenant_id, order_id)` 的部分唯一索引，仅覆盖非 `REJECTED` 记录；不同 key 同时申请同一订单时，冲突请求回查并返回已存在的有效退款，不再产生第二笔。被拒绝后允许新申请。键的生成与业务语义见 `backend/package/yuxi/services/enterprise_refund_workflow.py`、`enterprise_service.py` 和 `backend/package/yuxi/repositories/enterprise_repository.py`。已有数据库启动时补建该索引；若历史数据已有同订单多笔非拒绝退款，需先审计处理，系统不会自动删除业务记录。

错误统一为 `code/type/message/retryable`，Tool 返回 `{ok: false, error: ...}`，HTTP 路由映射为相应状态码。只有显式可重试的企业异常可进行有限退避；权限拒绝、参数错误、业务冲突不重试。实现见 `enterprise_errors.py` 和 `backend/server/routers/enterprise_router.py`。

当前 Demo 仅支持整单退款；申请金额小于订单实付金额时返回业务错误码 `PARTIAL_REFUND_NOT_SUPPORTED`，HTTP 422，不创建退款记录或将订单标记为已退款。

审批处理使用行锁串行化同一 `ApprovalTask` 的审核。只有首个待审决策能够修改退款与订单并触发原线程恢复；其余并发或重复审核返回 `APPROVAL_ALREADY_REVIEWED`（HTTP 409），不覆盖已提交决策。

测试包括重复自然语言请求、并发同键及不同键退款写入、拒绝后重新申请、非法工单状态迁移、审批重复处理与错误载荷。不能只看请求状态码；应核对数据库对象 ID、非拒绝退款数和关联审批任务数。
