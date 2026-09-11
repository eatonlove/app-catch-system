# 工作台接口 v1

所有/api接口使用管理员Bearer或登录HttpOnly会话；Cookie写请求需X-Requested-With: appcatch。/worker仅节点Bearer。单内部工作空间，不是多人权限系统。

POST /auth/login {password}；POST /auth/logout。GET /api/status返回nodes/counts/model_configured/model/daily_call_limit。
GET /api/catalog返回可执行采集入口字典。POST /api/jobs {request_key,recipe,context}；GET /api/jobs；POST /api/jobs/{id}/cancel；GET /api/jobs/{id}/result。
GET/POST /api/plans，POST体{name,catalog_id,enabled}；POST /api/plans/{id}/toggle。计划每日产生昨天任务，调度器5秒巡检、幂等键去重。
POST /api/analyses {use_model,country,store}；GET /api/analyses；GET /api/analyses/{id}返回状态和result，后者包含candidates/evidence/warnings以及可选model。
GET /api/feedback返回key→value；PUT /api/feedback/{key} {decision,qualification,note,experiment,evidence_refs}。develop必须已人工评估资格、有说明和引用。
错误401未登录，403缺CSRF头，409配置/租约/上下文冲突，422数据格式错误，429登录限流。前端所有空态/错误态来自实际接口，无模拟数据。

## v2：详情页面与分析方向

新增真实接口 `GET /api/jobs/{id}` 返回任务信息（不含租约凭证）；详情数据仍从 `/api/jobs/{id}/result` 读取。浏览器页面 `/collections/{id}`、`/reports/{id}` 支持直接访问、刷新与登录后返回；仅页面外壳公开，数据仍需管理员认证。

`GET /api/research-directions` 返回 `{id,title,description,prompt,version}` 数组。创建研究新增 `direction`（默认 comprehensive）、`guidance`（最多6000字符，可来自本地UTF-8 txt/md）字段。选择、补充提示词及实际完整 system prompt 在创建时快照保存于现有 filters JSON，不新增数据库列；后续模板变更不改变已排队任务。列表返回 filters 便于显示方向。报告返回 prompt_snapshot、实际模型证据ID、输入覆盖说明；旧报告继续可读。

模型结果仍使用既有 candidates/task/hypothesis/evidence_ids/unknowns 契约；不同方向改变研究任务与报告内容，不改变证据真实性约束。无模型报告不调用或保存为已执行AI提示词。前端无mock。
