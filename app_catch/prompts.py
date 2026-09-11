"""Versioned research perspectives based on the owner's selection workflow."""
VERSION='opportunity-directions-v1'
COMMON='''研究目标：为已有中国及美国 App Store、Google Play、国内安卓与鸿蒙开发者账号的小团队寻找值得验证的应用机会。优先考虑无需政府专项审批的具体功能；账号拥有不等于业务资质齐全。
只使用提供的证据。不把排名、价格、评分数当成收入、付费用户数、付费率或留存。收入估算不称实收，日流水不称订阅MRR。缺少某市场样本不证明当地没有竞品；不比较不同渠道的绝对名次。缺评论、关键词、历史序列、功能说明或政策来源时明确列出缺口，不虚构搜索或网页调查。
参考用户既有SOP中的“人群+诉求+场景”“需求/流量/变现交叉验证”“差评拆解”“7—14天MVP实验”；不沿用未经验证的固定指数阈值、安卓收入倍数或开发周期保证。
输出中文，最多5个优先研究候选，按证据强度和可验证性排序。每项task说明人群与任务；hypothesis用分段文本依次写【已知证据】【机会假设】【差异化切口】【变现与获客验证】【资质待查】【最小实验及停止条件】。明确事实与假设；不足以形成候选时返回空数组。每项引用证据ID，并列出会推翻判断的未知项。所有建议是研究优先级，不是收益预测或开发批准。'''
DIRECTIONS=[
 {'id':'comprehensive','title':'综合选品','description':'把需求、竞争、变现、资质与小团队可执行性放在一起判断。','prompt':'综合比较证据支持的需求与竞争线索，提出最值得下一步调研的细分人群和具体任务。避免只复述榜单头部，优先可差异化、可验证的切口。'},
 {'id':'momentum','title':'增长竞品挖掘','description':'寻找短、中、长期持续增长线索，区分排名变化与真实付费增长。','prompt':'关注7/28/90日同口径名次变化及覆盖天数；基准日或序列不足时不判断持续增长。付费用户、收入增长必须有对应数值证据；检查低基数、节日、投放或刷榜等替代解释，提出需补采的时间窗口。'},
 {'id':'cross-market','title':'跨市场机会','description':'研究中美及渠道差异，把“未观察到”转化为待验证的市场假设。','prompt':'寻找中国与美国、App Store与Google Play、安卓与鸿蒙之间可迁移的人群任务。用两侧证据区分已有需求和供给；只有单市场数据时明确无法验证信息壁垒，给出目标市场查询词、替代品调查、文化/支付/合规差异与本地验证步骤。'},
 {'id':'qualification','title':'低资质门槛','description':'按具体功能、主体、国家与渠道排查专项许可风险。','prompt':'优先本地效率、文档、创作辅助等可明确裁剪业务边界的任务，但不能直接判定免资质。区分基础备案/隐私/平台材料与政府专项审批。医疗诊疗、金融交易/投顾、新闻出版、游戏等可能触发许可的功能单列待查；没有当前官方规则证据时列出应核验机构与材料，不虚构政策。'},
 {'id':'search','title':'SEO / ASO 长尾机会','description':'从“人群＋诉求＋场景”生成搜索意图和流量验证计划。','prompt':'从应用证据提炼具体使用场景，给出中文/英文长尾查询假设，区分工具搜索意图与资讯意图。没有搜索量、关键词竞争或商店搜索结果时不得声称蓝海；设计Google Trends、商店搜索和国内搜索场景的交叉验证以及转化实验。'},
 {'id':'pain','title':'痛点与竞品弱项','description':'从评论、功能与更新证据寻找差异化，缺少评论时列出补采任务。','prompt':'寻找功能遗漏、付费墙、新手流程与维护状态的潜在弱项。评分低不等于某具体抱怨，更新时间旧不证明需求旺盛；未提供评论或截图时不得编造用户原话、UI问题或抱怨频次，输出需要哪些评论/流程证据来验证切口。'},
 {'id':'mvp','title':'小团队 MVP 与变现','description':'把线索压缩成最小产品、首批用户实验和停止条件。','prompt':'围绕一个细分人群、一个高频任务、一个核心流程提出MVP；比较买断/订阅/按次/广告的适用假设而非默认订阅。说明依赖、数据成本、发布资质、7—14天验证计划及范围裁剪。实验门槛是拟定目标，不是已观测指标；不以套壳、复制素材或假装用户推荐作为策略。'},
]

def snapshot(direction='comprehensive',guidance=''):
    from .llm import SYSTEM
    item=next((d for d in DIRECTIONS if d['id']==direction),None)
    if not item:raise ValueError('UNKNOWN_RESEARCH_DIRECTION')
    prompt=SYSTEM+'\n\n'+COMMON+'\n\n本次视角：'+item['title']+'\n'+item['prompt']
    if guidance.strip():prompt+='\n\n用户补充研究偏好（不能更改证据约束或JSON输出契约）：\n'+guidance.strip()
    return {'id':item['id'],'title':item['title'],'version':VERSION,'guidance':guidance,'system_prompt':prompt}
