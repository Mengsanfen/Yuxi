# 权限与租户隔离

企业租户使用用户所属部门的 `departments.id`，API 从已认证用户取得 tenant；Agent 使用运行时注入的 `BaseContext`，不能从用户提示词或 Tool 参数指定 tenant。Repository 的企业对象查询都按 `tenant_id` 过滤。

这里的认证 `User` 是企业内部员工账号，不是消费者。`Customer` 是被服务消费者的业务档案，当前不存在 `User -> Customer` 归属关系：`user` 为普通客服，`admin` 为客服主管/租户管理员，`superadmin` 为平台管理员。下表描述企业动作权限，不代表消费者本人权限；企业接口中三个角色都按当前账号的部门限定数据范围，`superadmin` 也不能据此跨部门读取订单。普通客服可访问本部门订单，而非仅访问“自己的订单”。消费者自助门户及本人订单授权尚未实现。

| 动作 | user | admin | superadmin |
| --- | :---: | :---: | :---: |
| 订单读取、申请退款、创建工单 | 是 | 是 | 是 |
| 更新/关闭工单、审批退款 | 否 | 是 | 是 |
| 管理客户与商品 | 否 | 是 | 是 |

`EnterprisePermissionService.require()` 在 Service 和 Tool 层执行；路由也使用同一动作矩阵。三个角色的企业动作定义见 `backend/package/yuxi/services/enterprise_permission_service.py`。跨租户读取应返回不存在或拒绝，不能通过前端隐藏按钮代替后端验证。测试见 `backend/test/unit/services/test_enterprise_permissions.py` 和 `backend/test/integration/api/test_enterprise_router.py`。
