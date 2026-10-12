# 安全边界与部署风险

已实现的企业边界：租户从认证/运行时上下文取得；API、Service、Tool 使用同一权限矩阵；Knowledge Agent 只读；检索文本隔离；Grounding 在模型检查前验证订单与退款事实；Trace 脱敏；退款和审批由数据库状态决定。测试见 `backend/test/unit/agents/`、`backend/test/unit/services/test_enterprise_permissions.py` 和企业 API/E2E 测试。

当前认证 `User` 仅代表企业内部客服/运营人员：`user` 是普通客服，`admin` 是客服主管/租户管理员，`superadmin` 是平台管理员。`Customer` 是被服务消费者档案，不具备登录身份，也没有与 `User` 的所有权绑定。企业接口按员工所属部门隔离，普通客服可读取本部门订单，不能将此解释为消费者只能查询本人订单；企业接口中的 `superadmin` 也受部门数据范围约束。消费者自助门户是未来工作，必须先增加消费者认证、账号与 Customer/订单绑定及服务端所有权校验，不能直接对外开放现有企业接口。

当前仓库仍有以下部署限制，不应将本地 Demo 直接暴露到公网：

1. `backend/package/yuxi/storage/minio/client.py` 将知识库图片放在公开可读的 `public` bucket；私有知识库图片可能被知道 URL 的人读取。生产化需要私有 bucket、鉴权读取或短期签名 URL，并验证旧对象迁移。
2. `backend/server/main.py` 的 CORS 现默认只允许两个本地开发来源；跨域部署需通过 `YUXI_CORS_ORIGINS` 配置逗号分隔的 HTTPS 来源列表并验证浏览器行为。不要配置 `*` 与凭证并用。
3. `docker-compose.yml` 默认开启演示账号种子且有示例密码。种子服务不再把密码写入日志，但已有日志可能保留旧值；生产应显式关闭种子、轮换所有示例凭证并检查历史日志。
4. 当前业务表通过项目现有建表/补表路径演进，缺少完整 Alembic 版本链；生产升级前应补数据库迁移与回滚演练。

上述风险不由前端隐藏链接或 README 声明消除。企业 Trace 脱敏与 Prompt Injection 检测也不能替代权限、网络和存储层的控制。
