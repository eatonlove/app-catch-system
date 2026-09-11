# 工作台接口 v1

所有/api接口使用管理员Bearer或登录HttpOnly会话；Cookie写请求需X-Requested-With: appcatch。/worker仅节点Bearer。单内部工作空间，不是多人权限系统。

POST /auth/login {password}；POST /auth/logout。GET /api/status返回nodes/counts/model_configured/model/daily_call_limit。
GET /api/catalog返回可执行采集入口字典。POST /api/jobs {request_key,recipe,context}；GET /api/jobs；POST /api/jobs/{id}/cancel；GET /api/jobs/{id}/result。
GET/POST /api/plans，POST体{name,catalog_id,enabled}；POST /api/plans/{id}/toggle。计划每日产生昨天任务，调度器5秒巡检、幂等键去重。
POST /api/analyses {use_model,country,store}；GET /api/analyses；GET /api/analyses/{id}返回状态和result，后者包含candidates/evidence/warnings以及可选model。
GET /api/feedback返回key→value；PUT /api/feedback/{key} {decision,qualification,note,experiment,evidence_refs}。develop必须已人工评估资格、有说明和引用。
错误401未登录，403缺CSRF头，409配置/租约/上下文冲突，422数据格式错误，429登录限流。前端所有空态/错误态来自实际接口，无模拟数据。
