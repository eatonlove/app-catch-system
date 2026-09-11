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

## v3：研究数据范围与可用性预览

GET /api/research-sources 返回采集批次列表（id/context/status/row_count/eligible/排除原因）。POST /api/research-preview 接收研究输入，返回不调用模型的数据覆盖、缺口、将送入模型的应用清单和source_ids。创建研究新增source_ids（可省略表示提交时匹配的全部完整批次；显式空数组拒绝）和evidence_limit（1—30，默认30）。创建时冻结批次ID，后续完成的采集不会悄悄进入已排队报告。国家筛选与勾选范围必须一致。旧客户端省略source_ids仍兼容。

报告保存source_overview：具体批次、记录数、覆盖日期、可比时间窗口、真实模型输入清单、抽样规则及缺口。旧报告以其已存证据重建来源视图，标记重建；缺少模型输入清单则显示未知，不倒推。新模型输出新增summary/data_gaps/next_steps，旧candidates契约继续可读。

## v4：持久化选品闭环（真实接口）

新增 ac_lab_records / ac_lab_history 两张本项目独占表；历史追加，机会更新采用 expected_version 乐观锁，冲突409。模型输出不会自动成为资格通过或立项结论。

- GET/POST /api/evidence：结构化来源、原文、国家、渠道、日期、质量、权利说明；GET /api/evidence/{id}。不可变记录，自带hash。
- GET/POST /api/opportunities：独立任务机会；GET/PUT /api/opportunities/{id}；GET .../history；POST .../review；POST .../status。country/store/track过滤。run_id指定固定快照分页，offset/limit；响应含as_of/source_coverage/is_partial/score_version。
- POST /api/opportunities/from-report {report_id,candidate_index,country,store}：将保存的AI假设及其真实引用转换成补证机会，按报告/候选/目标去重。不会自动评分类或放行。
- GET/POST /api/qualification-rules：人工核验规则（引用已登记证据）。每条规则不可变，修订另建；复核最长30天。机会功能/因子更新清除旧放行状态。
- GET/POST /api/score-runs；GET /api/score-runs/{id}：冻结机会、证据引用、审核版本、权重、分项、可信度及±20%权重敏感性。只允许今天创建快照；历史查看旧快照，拒绝伪造时点回测。
- GET/POST /api/experiments；GET /api/experiments/{id}；POST .../results：实验计划、预算、分母、观察窗、真实结果。结果追加，计算Wilson95%及贡献金额，未成熟续费不作失败。立项要求READY、MVP、主榜门槛及成熟真实付费和非负贡献，不自动外部执行。
- GET /api/observations；GET /api/growth?as_of=YYYY-MM-DD：独立口径日收入/下载观测的7/28/90相邻窗口。每窗口>=90%覆盖才计算log增长；不同比例/币种/来源不混合，负收入复核。
- POST /api/imports/preview {kind:evidence|observations|bundle,rows?,csv_text?,mapping?,defaults?}：真实JSON/CSV校验预览。映射为原列名→标准列名。返回id/errors/sample/can_commit；POST /api/imports {preview_id}确认后幂等入库。错误整批拒绝，不静默吞行。bundle为原schema1点点标准化批次。
- GET/POST /api/capabilities：实测批次覆盖+人工能力台账。VERIFIED必须引用证据。GET /api/backlog：未来能力和数据缺口文档。
- GET/POST /api/entities：人工跨商店映射，有理由/证据/审核人；不因名字自动合并。
- GET /api/lab/schemas：上述真实写接口的字段及校验Schema，供页面表单及导入模板生成。
- POST /api/jobs/{id}/retry：FAILED/PARTIAL/CANCELLED另建任务，保留原数据。人工导入不能当浏览器任务重试。

所有新增接口沿用现有认证与CSRF约束；不抓取任意用户URL，不发送外部消息。无mock适配器。

研究v4补充：AnalysisInput增加evidence_record_ids（最多100），创建时把选定证据原文和元信息保存为supplemental_evidence快照；与采集样本一同接受15/30条及40000字符输入预算。允许只使用真实补充证据研究。所有补充输入在预览/报告中明确为登记证据，不当作榜单记录。提示词方向扩展至13个。

POST /api/growth/{group_id}/evidence?as_of=YYYY-MM-DD：把服务器重新计算的同口径趋势与父证据引用保存为研究证据，之后可在AI输入中勾选。不会把增长换算成付费人数，也不会自动填机会因子。
