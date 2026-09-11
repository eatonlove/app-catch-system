# 正式部署记录 · 2026-09-11

- 网址：https://catch.meidaquan.com
- 已部署应用代码：`62a0cbf45cbc02e7d991ea3b99ddd8d9cd35b3ef`，main。
- 腾讯轻量云上海实例：`lhins-275fserw`，`122.51.180.226`。
- 独立目录：`/www/dk_project/dk_app/app-catch-system`。
- 独立 Compose 项目：appcatch；api、db、analyst。API/DB健康，analyst正常运行。
- 独立回环端口：127.0.0.1:18083；独立PostgreSQL数据库appcatch；网络appcatch_private。
- 数据卷：appcatch_appcatch-db、appcatch_model-cache；未接入共享Supabase。
- Nginx：`/www/server/panel/vhost/nginx/catch.meidaquan.com.conf`。
- TLS：`/etc/letsencrypt/live/catch.meidaquan.com/`，到期2026-12-10，certbot续期与现有nginx reload钩子已核对。
- 模型：千问平台 `deepseek-v4-flash-0731`，Base URL `https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 密钥：项目production.env，mode600；不得输出或提交。模型Key留在云端，Mac仅需专属worker token。

## 实测

公网/healthz返回上述提交；未登录API401；真实管理员登录、Secure/HttpOnly会话、目录读取与退出登录通过。浏览器正式登录页面正常显示。

云端实际模型请求成功，JSON schema与证据引用校验通过；187 tokens（181输入、6输出），没有生成虚构应用候选。只做接口验证，没有向业务任务队列写入测试任务或报告。38项本地测试与GitHub CI通过。

Mac节点当前未连接。后续按MAC_MINI_HANDOFF.md安装并做四入口现场验收。登录信息与专属Mac配置另存用户本机私密交付文件，均未进入Git。

## 发布与后续更新

服务器GitHub私有仓库没有认证，首次通过已校验Git bundle与SCP部署。后续可配置只读deploy key，或继续增量bundle与ff-only流程，不在服务器放用户GitHub账户token。服务器构建官方PyPI下载受阻，已使用本项目AC_PIP_INDEX_URL指向阿里云HTTPS镜像；宿主全局配置不变。

当前无既有本项目数据迁移，因此未做部署前数据库备份。后续有真实数据后使用deploy/cloud/backup.sh并安排恢复演练。本次未改动其他应用容器或数据库；上线后同机现有服务仍健康。
