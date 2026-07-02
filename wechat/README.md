# WeWe RSS 本地部署说明

本文档记录当前 Windows 本机上的 WeWe RSS 部署方式、启动关闭命令和常用维护命令。

## 当前部署信息

- 项目源码：`C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app`
- 访问地址：`http://localhost:4000/dash`
- RSS 服务地址：`http://localhost:4000/feeds`
- 服务端口：`4000`
- AUTH_CODE：`wewe-rss-local-20260701`
- WeWe RSS 版本：`v2.6.1`
- Node.js：便携版 `v20.20.2`
- pnpm：`9.15.9`
- 数据库：远程 MySQL，配置在 `wewe-rss-app\apps\server\.env`
- 当前自启方式：Windows 计划任务 `WeWeRSS`，用户登录后自动启动

> 注意：数据库连接串和密码只放在本机 `.env` 文件中，不要把 `.env` 提交到公开仓库。

## 目录结构

```text
wechat
├── README.md
├── WeWeRSS-All.opml
├── start.py
└── wewe-rss-app
    ├── apps
    │   ├── server\.env
    │   └── web\.env
    ├── scripts
    │   ├── start-wewe-rss.ps1
    │   ├── stop-wewe-rss.ps1
    │   ├── install-wewe-rss-task.ps1
    │   └── install-wewe-rss-service.ps1
    └── logs
```

## 手动启动

```powershell
cd "C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-wewe-rss.ps1
```

启动后打开：

```text
http://localhost:4000/dash
```

## 手动关闭

```powershell
cd "C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-wewe-rss.ps1
```

该脚本会关闭监听 `4000` 端口的 WeWe RSS 进程。

## 检查运行状态

检查端口：

```powershell
Get-NetTCPConnection -LocalPort 4000 -State Listen
```

检查页面：

```powershell
Invoke-WebRequest -Uri "http://localhost:4000/dash" -UseBasicParsing
```

返回 `StatusCode: 200` 表示管理页面可访问。

检查登录自启任务：

```powershell
Get-ScheduledTask -TaskName WeWeRSS
Get-ScheduledTaskInfo -TaskName WeWeRSS
```

## 登录自启任务

当前机器已注册计划任务 `WeWeRSS`，用户登录 Windows 后会自动启动 WeWe RSS。

重新注册或修复计划任务：

```powershell
cd "C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-wewe-rss-task.ps1
```

启动计划任务：

```powershell
Start-ScheduledTask -TaskName WeWeRSS
```

停止计划任务本身：

```powershell
Stop-ScheduledTask -TaskName WeWeRSS
```

如果还需要关闭正在监听端口的进程，再执行：

```powershell
cd "C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-wewe-rss.ps1
```

删除计划任务：

```powershell
Unregister-ScheduledTask -TaskName WeWeRSS -Confirm:$false
```

## 安装为真正的 Windows 服务

由于安装系统服务需要管理员权限，普通 PowerShell 无法完成服务注册。若要安装成真正的 Windows Service，请用“以管理员身份运行”的 PowerShell 执行：

```powershell
cd "C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-wewe-rss-service.ps1
```

安装成功后可使用：

```powershell
Get-Service -Name WeWeRSS
Start-Service -Name WeWeRSS
Stop-Service -Name WeWeRSS
Restart-Service -Name WeWeRSS
```

Windows 服务方式使用 NSSM 包装 PowerShell 启动脚本，日志输出在：

```text
C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app\logs
```

## 重新构建或更新

进入项目目录：

```powershell
cd "C:\Users\92410\Desktop\技术分享\ai-agent\wechat\wewe-rss-app"
$env:Path = "C:\Users\92410\Desktop\技术分享\ai-agent\tools\node-v20.20.2-win-x64;$env:Path"
```

安装依赖：

```powershell
pnpm install
```

生成 Prisma Client：

```powershell
pnpm --filter server exec prisma generate
```

执行数据库迁移：

```powershell
pnpm --filter server exec prisma migrate deploy
```

构建前后端：

```powershell
pnpm run -r build
```

重启：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-wewe-rss.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-wewe-rss.ps1
```

## 常见入口

- 管理后台：`http://localhost:4000/dash`
- RSS 聚合：`http://localhost:4000/feeds/all.rss`
- JSON 聚合：`http://localhost:4000/feeds/all.json`
- OPML 文件：`C:\Users\92410\Desktop\技术分享\ai-agent\wechat\WeWeRSS-All.opml`

第一次使用时，在管理后台添加微信读书账号并扫码登录，然后添加公众号源。未添加账号或订阅源时，部分 `/feeds` 接口可能响应较慢或没有内容，这是正常状态。

