# DeskSecretary PWA 移动端伴侣

把 DeskSecretary 的任务列表装进 iPhone（或任何手机），通过 GitHub 同步实现电脑/手机数据互通。

> **PWA 是什么？** 一个特殊的网页，加到手机主屏幕后看起来和原生 App 一模一样：
> - 全屏显示，没有浏览器地址栏
> - 有自己的图标
> - 支持离线缓存
> - **不需要 Apple 开发者账号、不需要上架 App Store**

---

## 工作原理

```
电脑 DeskSecretary ──push── GitHub ──read── iPhone PWA
                            ↑                  │
                            └──── push ────────┘ (写 inbox.json)
```

- **电脑端**：每次同步推 `desk_secretary.db` + `tasks.json`
- **手机端**：读 `tasks.json` 显示任务列表；新增任务写到 `inbox.json`
- **下次电脑端同步**：自动消费 `inbox.json`，把手机加的任务并入 SQLite

---

## 第一步：部署 PWA 到 GitHub Pages

PWA 静态文件位于 `desk-secretary/pwa/` 目录。需要把这个目录推到 GitHub 并启用 Pages。

### 方案 A：在现有同步仓库启用 Pages（推荐）

假设你的同步仓库是 `https://github.com/XYZJiangShan/WorkBuddy_Secretary`。

1. **把 PWA 目录推到仓库**

   PWA 文件已经放在 `desk-secretary/pwa/`，但 SyncService 同步的是另一个 Git 仓库（用户配置的 `sync_github_repo`）。你需要手动把 `pwa/` 目录复制并推送到 **同步仓库**：

   ```powershell
   # 假设你已经 clone 了同步仓库到 C:\xxx\WorkBuddy_Secretary
   cd C:\Users\Lenovo\WorkBuddy\20260330193344\desk-secretary
   robocopy pwa C:\xxx\WorkBuddy_Secretary\pwa /E
   cd C:\xxx\WorkBuddy_Secretary
   git add pwa
   git commit -m "feat: add PWA mobile companion"
   git push
   ```

2. **启用 GitHub Pages**

   - 打开 `https://github.com/XYZJiangShan/WorkBuddy_Secretary/settings/pages`
   - **Source** 选 `Deploy from a branch`
   - **Branch** 选 `main`，目录选 `/ (root)`
   - 保存，等待 1-2 分钟

3. **访问地址**

   ```
   https://xyzjiangshan.github.io/WorkBuddy_Secretary/pwa/
   ```

   > **重要：PWA 需要根目录可访问**——如果只想暴露 `pwa/` 子目录，地址要带 `/pwa/`，且 Service Worker 的 scope 仅在该子路径下生效（已在代码中处理为相对路径，无需修改）。

### 方案 B：独立 PWA 仓库（如果你的同步仓库是 private 不想公开）

由于 GitHub Pages 免费版只能部署 public 仓库的内容（除非有 Pro），如果你的同步仓库是 private 但又不想升级，可以：

1. 新建一个 **public** 仓库 `desksec-pwa`，专门放 PWA 静态文件
2. 把 `desk-secretary/pwa/` 内容推到这个新仓库的 `main` 分支根目录
3. 启用 Pages，地址会是 `https://xyzjiangshan.github.io/desksec-pwa/`

PWA 在配置时填的还是 **数据仓库**（同步仓库）的名字 + token，不影响功能。

---

## 第二步：准备 GitHub Personal Access Token

PWA **读取 tasks.json** 不需要 token（如果数据仓库是 public）；但如果数据仓库是 private，或者想 **添加任务（写入 inbox.json）**，必须有 token。

**生成步骤：**

1. 打开 https://github.com/settings/tokens?type=beta（推荐 fine-grained token）
2. 点 `Generate new token`
3. **Repository access** 选 `Only select repositories` → 勾选 `WorkBuddy_Secretary`
4. **Permissions** → `Repository permissions` → `Contents: Read and write`
5. 生成后复制 token（形如 `github_pat_xxx`），**只显示一次，请保存好**

> 也可以用 classic token（`https://github.com/settings/tokens`），勾选 `repo` 权限。建议用 fine-grained 更安全。

---

## 第三步：iPhone 添加到主屏幕

1. 用 iPhone Safari 打开 `https://xyzjiangshan.github.io/WorkBuddy_Secretary/pwa/`
2. 点底部 **分享按钮**（方框带向上箭头那个）
3. 滚动找到 **添加到主屏幕**
4. 点右上角 **添加**
5. 主屏幕出现 DeskSec 图标，点开就是全屏 App

> 必须用 **Safari** 添加，Chrome/微信内置浏览器无法正确生成 PWA 主屏图标。

---

## 第四步：首次配置

1. 打开主屏 DeskSec App
2. 点右上角 ⚙ 图标
3. 填写：
   - **GitHub 用户名**：`XYZJiangShan`
   - **仓库名**：`WorkBuddy_Secretary`
   - **分支**：`main`
   - **Token**：粘贴第二步生成的 token
4. 保存

App 会自动从 GitHub 拉取 `tasks.json` 显示任务列表。

---

## 第五步：让电脑端开始同步

确保 DeskSecretary 桌面端已经在设置里开启了同步：

- 打开桌面端 → ⚙ → 数据同步
- 勾选「启用 GitHub 同步」
- 仓库地址：`https://<你的token>@github.com/XYZJiangShan/WorkBuddy_Secretary.git`
- 同步间隔：30 分钟（或更短）
- 立即同步一次

**首次同步后**，仓库根目录会出现 `tasks.json`，PWA 即可读到数据。

---

## 使用流程

| 操作 | 入口 | 时效 |
|------|------|------|
| 查看今日任务 | PWA 打开自动加载 | 实时（取决于电脑端最后一次同步） |
| 手动刷新 | 点右上角 ↻ | 即时拉最新 |
| 添加任务 | 点右下角 ➕ | 立即写入 inbox.json |
| 同步到电脑 | 等电脑端定时同步 | 默认 30 分钟内 |

**关键：手机加的任务会在电脑端下一次同步时被并入。** 想立刻拉，可以在电脑端右键托盘图标手动同步。

---

## 第一版的限制

| 功能 | 状态 | 说明 |
|------|:---:|------|
| 查看今日任务 | ✅ | |
| 添加新任务 | ✅ | 写入 inbox.json，电脑端拉走合并 |
| 离线查看缓存 | ✅ | localStorage |
| 勾选/删除任务 | ❌ | v2 计划，需双向冲突合并 |
| AI 解析任务 | ❌ | 涉及 token，安全需求多 |
| 推送通知 | ❌ | iOS PWA 推送限制多，原生 App 才合适 |
| 周报/历史 | ❌ | v2 计划 |

---

## 数据安全提醒

- **数据仓库务必设为 private**（GitHub 个人账户免费支持 private + Pages 的组合不行，需要 Pro。如果你只能用 public 仓库，请勿在任务里写敏感信息）
- **Token 仅存在你手机的 localStorage 里**，不会传到其他地方
- **PWA 本身代码可以放 public 仓库**（只是静态资源，不含数据）

---

## 故障排查

**PWA 一直显示「未同步」**
- 检查配置：用户名、仓库名是否拼写正确
- 检查仓库根目录是否真的有 `tasks.json`（电脑端至少同步过一次）
- 检查 token 是否有 Contents 读权限

**添加任务失败**
- 确认 token 有 **写** 权限（Contents: Read and write）
- 检查浏览器控制台报错（在 Safari 里需要先开启「设置→Safari→高级→Web 检查器」）

**主屏图标白色没图案**
- 确认 manifest.json、icon-192.png、icon-512.png 都成功部署
- 卸载主屏图标重新添加

**离线打不开**
- Service Worker 需要 HTTPS（GitHub Pages 自带）
- 首次必须联网访问一次让 SW 缓存资源
