# 给 Mac mini 上 Codex 的执行指令

将本段文档交给 Mac mini 的 Codex。目标是在本机安装 app-catch-system 采集节点，连接已部署的腾讯云工作台；只操作本项目，不改镜析及其他业务。

## 已知与输入

仓库：<https://github.com/eatonlove/app-catch-system>（私有）。先确认 GitHub 有读取权限。

云端已部署，HTTPS origin 为 https://catch.meidaquan.com。需要从云端管理员安全取得专属 AC_WORKER_TOKEN（本机已生成 MacMini节点配置.env 私密交付文件）。不要要求用户把 token 发到聊天；指导写入本机未跟踪 env。无需数据库密码、模型 Key 或管理员密码。云端未部署时先完成依赖安装与官方登录，等待 origin 后再启动节点，不能使用示例域名试跑。

## 执行步骤

1. 选择独立目录；已有 checkout 先检查用户变更，再更新到 main，不覆盖本地更改。

```bash
git clone https://github.com/eatonlove/app-catch-system.git
cd app-catch-system
bash deploy/mac/install.sh
```

2. 安全编辑 `deploy/mac/worker.env`，填 HTTPS origin、节点 token、AC_WORK_DIR（独立绝对目录，例如项目下 data/remote-worker）、AC_RECIPE_DIR（项目下 configs/recipes 绝对路径）。shell source 格式，值用单引号，不要打印内容。执行 `chmod 600 deploy/mac/worker.env`。

3. 保持 macOS 图形用户会话，执行官方登录。若节点已经运行先停止；不接管日常 Chrome profile。

```bash
bash deploy/mac/stop.sh
bash deploy/mac/login.sh
bash deploy/mac/doctor.sh
```

在专用 Chromium 中由用户正常完成点点登录和验证码，看到榜单后回终端按回车。脚本不会复制日常 Chrome Cookie。若平台限制并发登录，协调现有账号使用，不绕过限制。

4. 先前台启动一次，云端工作台提交 iOS 美国工具畅销榜一次任务，核对结果后 Ctrl+C。

```bash
bash deploy/mac/run.sh
```

验收：节点在线；目标日期/国家/设备/类别正确；前100名连续无重复；JSON 保留来源、上下文、采集时间；目标未达则 PARTIAL，不改成成功。依次验证 Google Play 美国、华为工具、鸿蒙入口。若 UI 结构变化，修改本地配方/解析器、添加针对性验证后再推送，不把未验证配方标成可用。

5. 实页验证通过后启动本项目 LaunchAgent：

```bash
bash deploy/mac/start.sh
```

云端再开启每日计划。默认按中国时区每天抓取昨天，第一次启用会立即补昨天一份。停机多日不会自动补齐历史：手工创建缺日期任务，或后续增加回填计划。

## 运行、恢复与回报

- 启停：`start.sh` / `stop.sh`，只管理 `com.appcatch.worker`。
- 日志：项目 `data/remote-worker/logs`，运行结果：AC_WORK_DIR/runs。日志需按磁盘容量定期归档，不删除尚未确认上传的 bundle。
- 登录失效：节点暂停领取；stop → login → start；login 成功清除 login-required 标记。
- 断网：保存结果后重传，租约过期可重新领取；不要手动删 profile 锁文件。
- 24小时需机器通电、有网络并禁止自动系统睡眠，屏幕可关闭。LaunchAgent 在该用户登录后运行，不能保证重启后无人登录仍可启动浏览器。系统节能设置按用户现有用途调整。
- 升级：停止本项目节点 → 检查工作区 → 拉取已验收版本 → install → doctor → 单任务 → start。
- 请向用户报告提交 SHA、节点在线情况、四个入口各自采集行数/日期/状态、失败原因。仅报告脱敏结果，不上传 Cookie/profile、env 或包含用户账号信息的截图。

## 当前验收边界

开发机已核验可见 DOM、iOS 前100名、云端 API/队列与 Web 流程。Mac mini 专用 Python 浏览器会话的端到端采集正是本交接要完成的最后现场验收；不能把开发机的 DOM 观察当作已在此设备执行成功。
