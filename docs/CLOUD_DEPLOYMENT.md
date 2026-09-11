# 腾讯轻量云部署

部署形态：独立 Compose 项目 `appcatch`；PostgreSQL17、API、单实例 analyst；回环端口经过 Nginx HTTPS 暴露。参照镜析的云端队列与 Mac 主动拉取方式，但不共用镜析账号、数据库、卷、profile 或模型密钥。

## 1. 准备

需要 Linux Docker + Compose、Git、Python3、已指向本机的域名及 TLS 证书。先检查内存、磁盘、容器、端口与现有反代；三个容器分别限制 512MB，需预留宿主与现有业务余量。生产目录独立，例如 `/srv/app-catch-system`。镜析和其他项目的现有端口不是本项目默认端口，必须实查空闲值。

```bash
git clone https://github.com/eatonlove/app-catch-system.git /srv/app-catch-system
cd /srv/app-catch-system
python3 deploy/cloud/init-env.py
```

私有仓库使用有权限的 GitHub 登录或只读 deploy key。初始化交互输入空闲回环端口与管理员密码，生成数据库、管理员 API 和节点三类独立密钥。脚本不会覆盖已有配置。

## 2. 模型与启动

安全编辑 `deploy/cloud/production.env`：

|变量|含义|
|---|---|
|AC_LLM_ENDPOINT|HTTPS OpenAI-compatible Base URL，通常以 `/v1` 结尾；适配器会追加 `/chat/completions`，不要重复填写|
|AC_LLM_MODEL|供应商模型名|
|AC_LLM_API_KEY|仅在云端保存|
|AC_MODEL_DAILY_LIMIT|每天最多启动的模型研究任务数，默认10；是次数上限，不是人民币预算|

未填写模型三项时只能执行无模型研究。用户需要在报告生成时主动选择模型研究；每日计划不会默认产生模型费用。供应商 Key 的预算也应在其控制台设置。

```bash
bash deploy/cloud/release.sh "$(git rev-parse HEAD)"
```

该命令要求当前干净工作树与指定完整提交一致，仅操作 appcatch 的 Compose 服务。首次建表由程序执行，当前是 v1 初始 schema；未来字段变更必须附带独立迁移，不能假设 create_all 会升级已有列。

## 3. HTTPS 与验收

将 `deploy/cloud/nginx.conf.example` 的域名、证书、端口替换为已确认值，放入本系统独立站点配置。先 `nginx -t`，再 reload。不得覆盖镜析等现有站点。公网只开放 HTTPS；数据库不映射宿主端口，API 仅绑定127.0.0.1。

检查 `/healthz` 返回成功和正确 release；浏览器登录；未登录 `/api/status` 应401。安全转交 **仅 AC_WORKER_TOKEN 与 HTTPS origin** 给 Mac。先启动一个节点完成单任务，再创建每日计划。正式验收应覆盖本地断网、任务取消、重新登录和模型小额调用。

## 4. 运维

```bash
docker compose --env-file deploy/cloud/production.env -f deploy/cloud/compose.yml -p appcatch ps
bash deploy/cloud/backup.sh /安全备份目录
```

备份包含业务数据，应保留云外加密副本并做恢复演练。恢复时停止本项目 api/analyst，使用 pg_restore 将 custom-format dump 向独立恢复库导入并验收后切换；不能直接向未经确认的线上库覆盖。日志不要输出 env、Authorization、浏览器会话或模型 Key。

版本回退：保留升级前数据库备份，checkout 已验收提交，再执行 release.sh；若有 schema 变更先按对应迁移说明处理。本项目脚本不删除卷，不执行全局 Docker 清理。当前未实现自动备份调度、告警推送与数据归档；这些需要结合实际容量和运维渠道配置。

生产部署仍需真实域名/TLS、可用服务器目录和端口、模型配置。交付时仅进行了本地容器与临时数据库验证，尚未对现有腾讯云服务作修改。
