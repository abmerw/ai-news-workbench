#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finish_setup.py - 把 ainews-standalone 推送到 GitHub 仓库并完成上线。

前置：账号下已有一个 Public 空仓库（名字任意，脚本会自动改成 GH_REPO）。
运行：GITHUB_TOKEN=xxx python3 scripts/finish_setup.py

流程：
  1. 定位仓库：目标名不存在时，自动把账号下的仓库改名为目标名
     （GitHub 会把中文仓库名规范化成 "-"，这一步正好修正它）
  2. 写权限预检：用 .nojekyll 空文件做最小写探针，只读令牌立即精确报错
  3. 通过 API 上传其余文件（失败自动回退 git push）
  4. 开启 GitHub Pages（main 分支 / 根目录）
  5. 手动触发一次抓取工作流
  6. 回读确认文件与 Pages 状态，输出线上地址

环境变量：
  GITHUB_TOKEN   必填，需带 repo + workflow 权限（推荐 classic PAT）
  GH_OWNER       仓库所有者，默认 abmerw
  GH_REPO        目标仓库名，默认 ai-news-workbench
  GH_RENAME_FROM 指定要改名的旧仓库名；不填则自动选账号下唯一的仓库
"""
import os
import sys
import json
import base64
import subprocess
import urllib.request
import urllib.error

OWNER = os.environ.get("GH_OWNER", "abmerw")
REPO = os.environ.get("GH_REPO", "ai-news-workbench")
RENAME_FROM = os.environ.get("GH_RENAME_FROM", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
FULL = "%s/%s" % (OWNER, REPO)
SITE = "https://%s.github.io/%s/" % (OWNER, REPO)

SKIP_DIRS = {".git", "__pycache__"}
SKIP_EXT = {".pyc", ".zip"}
PROBE_FILE = ".nojekyll"
READ_ONLY = "Resource not accessible by integration"


def http(method, path, body=None, timeout=40):
    url = API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ainews-finish-setup",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"message": raw[:300]}
    except Exception as e:
        return -1, {"message": str(e)}


def list_files():
    out = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if os.path.splitext(n)[1] in SKIP_EXT:
                continue
            rel = os.path.relpath(os.path.join(base, n), ROOT).replace(os.sep, "/")
            if rel != PROBE_FILE:
                out.append(rel)
    return sorted(out)


def report_readonly(where, code, msg):
    print("")
    print("  %s 失败：HTTP %s %s" % (where, code, msg))
    if READ_ONLY in str(msg):
        print("  诊断：当前令牌是 GitHub 应用令牌（ghu_ 开头、无 OAuth scopes），只读。")
        print("        permissions.push=true 只代表你本人对仓库的权限，不代表令牌能写入。")
        print("  处理：换一张带 repo 与 workflow 权限的 Personal Access Token 后重跑本脚本。")
        print("        GitHub -> 头像 -> Settings -> Developer settings")
        print("        -> Personal access tokens -> Tokens (classic) -> Generate new token")
        print("        -> 勾选 repo 与 workflow -> 复制 ghp_ 开头的令牌")
    print("")


def resolve_repo():
    """定位仓库；目标名不存在时把账号下的仓库自动改成目标名。"""
    code, d = http("GET", "/repos/" + FULL)
    if code == 200:
        print("[1/6] 仓库就绪: %s | private=%s | 空仓库=%s"
              % (FULL, d.get("private"), d.get("size") == 0))
        return True

    print("[1/6] 目标仓库 %s 不存在，查找账号下的仓库…" % FULL)
    c2, repos = http("GET", "/user/repos?per_page=100")
    candidates = []
    if c2 == 200 and isinstance(repos, list):
        for r in repos:
            if str(r.get("owner", {}).get("login", "")).lower() == OWNER.lower():
                candidates.append(r)
    if not candidates:
        print("    账号下没有可改名的仓库。请新建 Public 空仓库：")
        print("    https://github.com/new?name=%s&visibility=public" % REPO)
        print("    名称填 %s、选 Public、不要勾 README。" % REPO)
        return False

    old = RENAME_FROM or (candidates[0]["name"] if len(candidates) == 1 else "")
    if not old:
        print("    账号下有多个仓库，请指定要改名的那个：GH_RENAME_FROM=<仓库名>")
        for r in candidates:
            print("      - %s" % r["name"])
        return False

    print("    发现仓库 %s/%s，尝试改名为 %s…" % (OWNER, old, REPO))
    c3, d3 = http("PATCH", "/repos/%s/%s" % (OWNER, old), {"name": REPO})
    if c3 != 200:
        report_readonly("改名", c3, d3.get("message", ""))
        return False
    print("    改名成功，仓库现为 %s" % FULL)
    return True


def probe_write():
    """用 .nojekyll 空文件做最小写探针，提前识别只读令牌。"""
    code, d = http("PUT", "/repos/%s/contents/%s" % (FULL, PROBE_FILE),
                   {"message": "chore: enable GitHub Pages", "content": ""})
    if code in (200, 201):
        print("[2/6] 写权限正常（%s 已写入）" % PROBE_FILE)
        return True
    report_readonly("写权限预检", code, d.get("message", ""))
    return False


def rest_upload(rels):
    ok, failed = True, []
    for rel in rels:
        with open(os.path.join(ROOT, rel), "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")
        body = {"message": "chore: add " + rel, "content": content}
        code, cur = http("GET", "/repos/%s/contents/%s" % (FULL, rel))
        if code == 200 and isinstance(cur, dict) and cur.get("sha"):
            body["sha"] = cur["sha"]
        code, d = http("PUT", "/repos/%s/contents/%s" % (FULL, rel), body)
        if code in (200, 201):
            print("      + " + rel)
        else:
            print("      ! %s -> HTTP %s %s" % (rel, code, d.get("message", "")[:110]))
            ok = False
            failed.append(rel)
    return ok, failed


def git_push():
    """回退路径：git 智能 HTTP 用 x-access-token + Basic 认证。"""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "/bin/echo"
    pre = [
        ["git", "-C", ROOT, "init", "-q"],
        ["git", "-C", ROOT, "checkout", "-q", "-B", "main"],
        ["git", "-C", ROOT, "add", "-A"],
        ["git", "-C", ROOT, "-c", "user.name=ainews-bot",
         "-c", "user.email=ainews-bot@users.noreply.github.com",
         "commit", "-q", "-m", "feat: AI 资讯工作台独立版（GitHub Pages + Actions 抓取）"],
    ]
    for cmd in pre:
        try:
            subprocess.run(cmd, env=env, capture_output=True, timeout=40)
        except Exception:
            pass
    basic = base64.b64encode(("x-access-token:" + TOKEN).encode()).decode()
    push = [
        "git", "-C", ROOT,
        "-c", "http.extraheader=AUTHORIZATION: basic " + basic,
        "-c", "http.version=HTTP/1.1",
        "push", "-f", "-u", "https://github.com/%s.git" % FULL, "main",
    ]
    try:
        r = subprocess.run(push, env=env, capture_output=True, timeout=120)
        msg = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
        return r.returncode == 0, msg[-500:]
    except Exception as e:
        return False, str(e)


def push_all(rels):
    print("[3/6] 通过 API 上传 %d 个文件…" % len(rels))
    good, failed = rest_upload(rels)
    if good:
        print("      全部上传成功")
        return True
    print("  以下文件上传失败：%s" % ", ".join(failed))
    print("  尝试 git push 作为回退…")
    ok, msg = git_push()
    if ok:
        print("      git push 成功")
        return True
    print("      git push 也未成功：")
    for line in msg.splitlines()[-4:]:
        print("      | " + line.strip())
    return False


def enable_pages():
    code, d = http("GET", "/repos/%s/pages" % FULL)
    if code == 200:
        print("[4/6] Pages 已开启: %s" % d.get("html_url", SITE))
        return True
    code, d = http("POST", "/repos/%s/pages" % FULL,
                   {"source": {"branch": "main", "path": "/"}})
    if code in (201, 204, 200):
        print("[4/6] Pages 已开启")
        return True
    print("[4/6] Pages 自动开启失败: HTTP %s %s" % (code, d.get("message", "")[:160]))
    print("      请在仓库 Settings -> Pages 手动选 main / (root)。地址仍是 %s" % SITE)
    return False


def dispatch():
    code, d = http("POST", "/repos/%s/actions/workflows/update.yml/dispatches" % FULL,
                   {"ref": "main"})
    if code in (200, 201, 204):
        print("[5/6] 已触发一次抓取工作流")
        return True
    print("[5/6] 手动触发失败（HTTP %s %s）；整点自动任务不受影响。"
          % (code, d.get("message", "")[:120]))
    return False


def verify():
    """确定性回读：确认主页文件与数据文件确实在仓库里。"""
    checks = []
    for rel in ("index.html", "data/ainews.json"):
        code, d = http("GET", "/repos/%s/contents/%s" % (FULL, rel))
        checks.append((rel, code == 200))
    code, _ = http("GET", "/repos/%s/pages" % FULL)
    ok = all(v for _, v in checks) and code == 200
    print("[6/6] 回读校验: %s | Pages=%s"
          % (", ".join("%s=%s" % (r, "OK" if v else "缺失") for r, v in checks),
             "OK" if code == 200 else "未开启"))
    return ok


def main():
    if not TOKEN:
        print("缺少 GITHUB_TOKEN 环境变量")
        return 2
    print("目标: %s" % FULL)
    print("")
    if not resolve_repo():
        return 3
    if not probe_write():
        return 4
    rels = list_files()
    print("")
    pushed = push_all(rels)
    print("")
    enable_pages()
    dispatch()
    verified = verify()
    print("")
    print("=" * 60)
    print("线上地址: %s" % SITE)
    print("数据文件: %sdata/ainews.json" % SITE)
    if verified and pushed:
        print("状态: 文件与 Pages 均已回读确认，构建通常 1-3 分钟内生效。")
    else:
        print("状态: 仍有未通过项，请按上面各步提示补齐。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
