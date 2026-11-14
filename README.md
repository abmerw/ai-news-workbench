# AI 讯息查阅台（独立版）

一个纯静态的 AI 资讯工作台：收录、追踪、复盘、板块速览。
静态托管在 GitHub Pages，数据由 GitHub Actions 每小时抓取，**不依赖任何外部服务或后端**。

- 站点：`https://abmerw.github.io/ai-news-workbench/`
- 数据：`data/ainews.json`
- 抓取：`scripts/fetch.py`（只用 Python 标准库）
- 手机：浏览器打开站点 → 分享 → 添加到主屏幕，即可全屏使用（PWA）

## 首次上线（2 步）

1. 在 GitHub 新建 **Public** 空仓库。名字任意，但**不要填中文**——GitHub 会把中文
   仓库名规范化成 `-`，导致 Pages 地址变成 `https://<用户名>.github.io/-/`。
   推荐直接填 `ai-news-workbench`，不要勾 README / .gitignore / License。
2. 运行 `GITHUB_TOKEN=xxx python3 scripts/finish_setup.py`：
   自动定位仓库（名字不对会自动改名）、预检写权限、上传全部文件、开 Pages、
   触发一次抓取、回读确认，最后打印站点地址。
   也可自行 `git remote add origin <仓库地址> && git push -u origin main`。

**令牌要求**：必须是带 `repo` 与 `workflow` 权限的 **Personal Access Token（classic，ghp_ 开头）**。
GitHub 应用令牌（`ghu_`）是只读的，写操作会返回 `403 Resource not accessible by integration`；
脚本会在写权限预检这一步立即报错并给出精确指引，不做无效重试。

GitHub Actions 的 `GITHUB_TOKEN` 由仓库自动提供，与推送用的令牌无关，
因此自动更新不需要任何额外密钥。

可选环境变量：`GH_OWNER`（默认 abmerw）、`GH_REPO`（默认 ai-news-workbench）、
`GH_RENAME_FROM`（指定要改名的旧仓库名，不填则自动选账号下唯一的仓库）。

## 结构

```
index.html                 单文件工作台（零外链、零 CDN，内联 PWA manifest 与图标）
sw.js                      网络优先 service worker（在线拿最新，离线用缓存）
data/ainews.json           页面读取的数据文件（Actions 每小时更新）
scripts/fetch.py           抓取 RSS → 生成 JSON
scripts/finish_setup.py    一键上线（推送 + 开 Pages + 触发抓取）
.github/workflows/update.yml  每小时定时任务
.nojekyll                  Pages 必需
```

## 数据怎么来

`scripts/fetch.py` 抓取以下资讯源的 RSS，过滤 AI 相关、只收中文标题，按标题去重后合并进 `data/ainews.json`：

- 量子位 `https://www.qbitai.com/feed`
- 雷锋网 `https://www.leiphone.com/feed`
- 钛媒体 `https://www.tmtpost.com/rss.xml`
- IT之家 `https://www.ithome.com/rss/`

改源只需要改 `scripts/fetch.py` 顶部的 `SOURCES`，单个源挂掉会跳过，不影响其他源。

**能做什么**：标题、来源、链接、摘要、分类、场景、重要度、从摘要里抽一个数字。
**不做什么**：不编造流程图。拆不出真实步骤的条目，`flow` 留空，卡片自动降级成「要点」单格——宁可少画，也不给假信息。

## 手动更新一次

Actions 页面 → `update-feed` → `Run workflow`。
或者本地：

```bash
python3 scripts/fetch.py          # 抓取并写入
python3 scripts/fetch.py --dry-run  # 只看会抓到什么，不写文件
```

## 你的数据存在哪

已读状态、备注、待深读、删除记录只存在**你打开页面的那台设备的浏览器里**（localStorage），
不会写回仓库，也不会跨设备同步。换设备或清缓存前，请用页面上的「导出 JSON」备份，换设备后「导入恢复」。

页面上的「新增资讯」只加在本机，不会进 `data/ainews.json`；想长期保留请导出备份。

## 手机使用（添加到主屏幕）

**推荐入口**：`https://abmerw.github.io/ai-news-workbench/`

1. 用手机浏览器（iPhone 用 Safari，Android 用 Chrome）打开上面的地址。
2. iPhone：点底部分享按钮 → 「添加到主屏幕」；Android：右上角菜单 → 「添加到主屏幕 / 安装应用」。
3. 桌面出现「AI 讯息台」图标，打开即全屏、无地址栏。

`index.html` 内联了 PWA manifest 与图标（零外链）；`sw.js` 用网络优先策略，
联网时永远加载最新版本，断网时用上次缓存。每小时的新资讯由 GitHub Actions 写入
`data/ainews.json`，打开页面会自动拉取合并。

### 旧入口说明

之前添加到桌面的图标指向 `https://aeb88c6f4936e1e21.app.workbuddy.host/...`（WorkBuddy 托管）。
该站点已更新为同一份页面，并把数据源直接指向 GitHub Pages 的数据文件（该文件允许跨域读取），
所以旧图标打开也是最新内容、也能持续自动更新；页面底部会提示一次迁移到新地址。
但托管仍在旧平台，长期建议删掉旧图标，用新地址重新添加一次。

## 换域名 / 迁移

整站就是三个部分（页面、数据、抓取脚本），换托管只需要把仓库内容搬到新地方，页面里的数据路径是相对路径，不用改。
