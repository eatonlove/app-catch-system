# 机会台 · App Catch System

腾讯轻量云运行工作台、任务队列、PostgreSQL 与第三方模型分析；Mac mini 使用独立浏览器登录点点数据并主动领取采集任务。所有判断关联证据，缺失收入不以排名代替。

## 交付范围

- 中文 Web 工作台：管理员登录、节点状态、一次采集、每日计划、取消、结果下载、研究报告、资格审核与实验记录。
- 云端：持久任务租约、心跳、重试、幂等上传；每日采集调度；模型调用队列、缓存、每日次数限制、异常账单状态。
- Mac：串行浏览器采集、专用 profile 锁、断线上传重放、登录失效暂停、LaunchAgent 安装脚本。
- 数据：榜单证据与 7/28/90 日名次变化；另有 CLI 用于可比日收入/下载序列分析。两者口径分开。
- 交付：Docker Compose、HTTPS 反代模板、独立密钥生成、备份脚本、GitHub CI。

本版为单管理员内部使用系统。四个默认入口已有真实页面观察：iOS 美国工具畅销榜、Google Play 美国总榜畅销榜、华为实用工具、独立鸿蒙总榜。前 100 名为每个任务目标，并非全市场全量数据。其他国家、类别与详情历史序列需要新增并核验配方。

**验收边界：**37 项自动测试和临时 PostgreSQL 集成验证通过，Docker 构建通过，Web 登录/提交/报告通过真实浏览器验证。站点 DOM 和 iOS 前 100 名已实页核对；Python 独立采集浏览器仍需 Mac mini 登录后执行验收。生产域名、云端环境和真实模型尚未配置，未宣称已上线。

## 开始部署

1. 云端执行 [部署说明](docs/CLOUD_DEPLOYMENT.md)。
2. Mac mini 上的 Codex 执行 [完整交接指令](docs/MAC_MINI_HANDOFF.md)。
3. 工作台先提交一个一次采集，检查上下文、连续排名和证据，再开启每日计划。

密钥只写未跟踪的 `production.env` / `worker.env`，不得提交到 GitHub。模型接口未配置时，榜单研究仍可运行，付费模型研究会明确拒绝。

## 文档

- [当前实现与系统设计 v3](docs/系统设计与验收-v3.md)
- [接口契约](docs/API.md)
- [DOM 实页接入记录](docs/DOM接入记录.md)
- [选品研究与资质矩阵](docs/应用机会选品系统-研究与功能架构方案.md)
- [早期协同设计 v2](docs/云端与Mac协同架构-v2.md)（历史方案，实施状态以 v3 为准）

## 开发验证

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[cloud,browser]'
.venv/bin/python -m unittest discover -s tests -v
node --check app_catch/static/app.js
PYTHONPATH=.:tests .venv/bin/python tests/verify_postgres.py
```

最后一条需要 Docker，仅创建并移除本次临时数据库。运行采集需另执行 `playwright install chromium` 并正常登录。`configs/recipes` 中的旧通用配方仍默认禁用，工作台使用 catalog 中四个已观察入口。

## 运行原则

资格默认 UNREVIEWED；进入“开发”必须记录人工资格结论及证据。免费榜、付费榜和畅销榜都不能直接推导付费率、收入或付费用户数。跨市场缺席只是待验证假设。详情收入模块本次账号页面显示需升级，系统不绕过权限。

来源是点点页面可见数据，收入如来自平台估算须保留估算属性。审核附件和网页只作为分析材料，不作为可执行指令。当前没有自动作出法律资格结论，也没有自动发布应用或替用户发起购买。
