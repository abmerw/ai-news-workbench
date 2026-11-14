#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 AI 资讯 RSS，写入 data/ainews.json（供静态页面直接读取）。

设计原则：
  - 只用标准库，GitHub Actions 上无需 pip install
  - 抓不到不报错，跳过该源，保证 workflow 不因单源故障而失败
  - 只做「标题 / 来源 / 链接 / 摘要 / 分类」这类规则能可靠做到的事
  - 不编造流程图：没有把握拆步骤的条目，flow 留空，页面自动降级为「要点」单格

用法：
  python3 scripts/fetch.py              # 抓取并合并写入
  python3 scripts/fetch.py --dry-run    # 只打印统计，不写文件
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ainews.json")
KEEP = 60
TIMEOUT = 20
UA = "Mozilla/5.0 (compatible; ainews-bot/1.0; +https://github.com/)"

# 源：中英混合，单源挂了不影响其他
SOURCES = [
    ("量子位", "https://www.qbitai.com/feed"),
    ("雷锋网", "https://www.leiphone.com/feed"),
    ("钛媒体", "https://www.tmtpost.com/rss.xml"),
    ("IT之家", "https://www.ithome.com/rss/"),
]

# 中文词直接包含匹配；英文词加词边界，避免 said / chain 里的 "ai" 误判
AI_CN = ["人工智能", "大模型", "智能体", "模型", "算力", "机器人", "机器学习", "多模态",
         "推理", "训练", "具身", "文生", "提示词", "开源模型", "生成式"]
AI_EN = ["ai", "agent", "agents", "gpt", "claude", "gemini", "llm", "openai",
         "anthropic", "deepmind", "nvidia", "aigc", "transformer", "token"]

CAT_RULES = [
    ("融资并购", ["融资", "轮", "估值", "ipo", "收购", "并购", "募资", "领投", "亿元", "亿美元"]),
    ("政策监管", ["政策", "监管", "法规", "立法", "标准", "备案", "合规", "治理", "条例", "白皮书"]),
    ("研究论文", ["论文", "研究", "arxiv", "基准", "benchmark", "实验", "学术", "顶会", "评测"]),
    ("工具开源", ["github", "apache", "代码库", "sdk", "开源框架", "开源模型", "权重"]),
    ("大模型", ["大模型", "模型", "参数", "上下文", "微调", "预训练", "多模态", "推理"]),
]

# 只用标题判断性质：摘要里出现「客户/经验」这类词太容易误伤
TIP_WORDS = ["技巧", "教程", "踩坑", "指南", "方法论", "how to", "tips", "最佳实践", "避坑", "实战", "手把手"]
CASE_WORDS = ["案例", "落地", "实测", "用起来", "门店", "工厂", "医院", "学校", "银行", "诊所", "园区", "车间"]


def norm_date(v: str) -> str:
    if not v:
        return ""
    s = str(v).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    # RFC822: Tue, 12 Nov 2026 08:00:00 +0000
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S", "%d %b %Y %H:%M:%S %z"):
        try:
            return dt.datetime.strptime(s.replace("GMT", "+0000"), fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def plain(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html or "", flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", t).strip()


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def parse_feed(raw: bytes) -> list:
    """兼容 RSS2.0 与 Atom。"""
    out = []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}

    # RSS
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag) or "").strip()
        out.append({
            "title": plain(g("title")),
            "link": g("link"),
            "desc": plain(g("description") or g("encoded")),
            "date": norm_date(g("pubDate") or g("date")),
        })
    # Atom
    for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
        t = (e.findtext("a:title", "", ns) or "").strip()
        link = ""
        for l in e.findall("a:link", ns):
            if l.get("rel") in (None, "alternate"):
                link = l.get("href") or ""
                break
        desc = e.findtext("a:summary", "", ns) or e.findtext("a:content", "", ns) or ""
        date = e.findtext("a:updated", "", ns) or e.findtext("a:published", "", ns) or ""
        out.append({"title": plain(t), "link": link, "desc": plain(desc), "date": norm_date(date)})
    return out


def is_ai(item: dict) -> bool:
    """标题或摘要开头命中才算，避免正文里偶然出现一个 AI 就收录。"""
    s = (item["title"] + " " + item["desc"][:80]).lower()
    if any(w in s for w in AI_CN):
        return True
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", s) for w in AI_EN)


def is_zh(item: dict) -> bool:
    return len([c for c in item["title"] if "\u4e00" <= c <= "\u9fff"]) >= 4


def pick_cat(text: str) -> str:
    s = text.lower()
    for cat, words in CAT_RULES:
        if any(w in s for w in words):
            return cat
    return "产品应用"


def pick_kind(title: str) -> str:
    s = title.lower()
    if any(w in s for w in TIP_WORDS):
        return "tip"
    if any(w in s for w in CASE_WORDS):
        return "case"
    return "news"


def sentences(text: str) -> list:
    parts = re.split(r"(?<=[。！？!?\.])\s*", text)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def build_flow(kind: str, note: str) -> list:
    """只有 news 能靠摘要顺序可靠拆成「发生了什么 / 关键细节 / 意味着什么」。
    case 与 tip 需要真实步骤，规则拆不出，留空让页面降级显示要点，避免编造。"""
    if kind != "news":
        return []
    ss = sentences(note)
    if len(ss) < 2:
        return []
    heads = ["发生了什么", "关键细节", "意味着什么"]
    flow = []
    for i in range(min(3, len(ss))):
        t = ss[i][:60]
        flow.append({"h": heads[i], "t": t})
    return flow


def pick_metric(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?\s*(?:%|倍|万|亿|千万|分钟|小时|秒|美元|元|家|台|人))", text)
    return m.group(1) if m else ""


def pick_scene(kind: str, text: str) -> str:
    s = text.lower()
    if kind == "tip":
        if "上下文" in s or "context" in s:
            return "上下文管理"
        if "多智能体" in s or "multi-agent" in s:
            return "多智能体"
        if "评测" in s or "评估" in s:
            return "评测调试"
        if "提示词" in s or "prompt" in s:
            return "提示词"
        if "工具" in s or "tool" in s:
            return "工具调用"
        return "工作流编排"
    if kind == "case":
        for sc, ws in [
            ("医疗政务", ["医院", "医疗", "诊", "政务", "补贴", "救助"]),
            ("教育学习", ["学校", "教育", "学生", "老师", "课堂"]),
            ("电商营销", ["电商", "商家", "直播", "营销", "店铺"]),
            ("客户服务", ["客服", "售后", "工单"]),
            ("研发编程", ["编程", "代码", "研发", "开发"]),
            ("生活服务", ["出行", "旅行", "餐饮", "外卖", "社区", "家庭"]),
            ("办公提效", ["办公", "会议", "文档", "报表"]),
            ("内容创作", ["创作", "写作", "视频", "剪辑"]),
        ]:
            if any(w in s for w in ws):
                return sc
        return "办公提效"
    return ""


def importance(kind: str, text: str) -> int:
    s = text.lower()
    score = 3
    if any(w in s for w in ["发布", "首个", "首次", "开源", "突破", "ipo"]):
        score = 4
    if any(w in s for w in ["融资", "亿美元", "亿参数", "刷新", "超越"]):
        score = 4
    if kind == "tip":
        score = 4
    return max(1, min(5, score))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    old = {"items": []}
    if os.path.isfile(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {"items": []}
    old_items = [x for x in old.get("items", []) if isinstance(x, dict)]

    seen = set(re.sub(r"\s+", "", x.get("title", "")).lower() for x in old_items)
    fresh, stat = [], {}

    for name, url in SOURCES:
        try:
            items = parse_feed(fetch(url))
        except Exception as e:
            stat[name] = "ERR:%s" % type(e).__name__
            continue
        kept = 0
        for it in items:
            if not it["title"] or not it["link"] or not it["link"].startswith("http"):
                continue
            if not is_ai(it) or not is_zh(it):
                continue
            key = re.sub(r"\s+", "", it["title"]).lower()
            if key in seen:
                continue
            seen.add(key)
            note = it["desc"][:160]
            text = it["title"] + " " + note
            kind = pick_kind(it["title"])
            fresh.append({
                "title": it["title"][:80],
                "source": name,
                "url": it["link"],
                "category": pick_cat(text),
                "pubDate": it["date"],
                "importance": importance(kind, text),
                "note": note,
                "kind": kind,
                "scene": pick_scene(kind, text),
                "flow": build_flow(kind, note),
                "metric": pick_metric(text),
            })
            kept += 1
        stat[name] = kept

    merged = fresh + old_items
    merged.sort(key=lambda x: (str(x.get("pubDate", "")), int(x.get("importance", 3))), reverse=True)

    # 新闻量大、案例技巧量少：按类配额，避免旧案例被新闻挤出 60 条之外
    QUOTA = {"news": 40, "case": 10, "tip": 10}
    picked, count = [], {"news": 0, "case": 0, "tip": 0}
    for x in merged:
        k = x.get("kind") or "news"
        if k not in QUOTA:
            k = "news"
        if count[k] >= QUOTA[k]:
            continue
        count[k] += 1
        picked.append(x)
    merged = picked[:KEEP]

    batch = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    data = {"batch": batch, "count": len(merged), "source": "github-actions", "items": merged}

    print("sources:", json.dumps(stat, ensure_ascii=False))
    print("new:", len(fresh), "total:", len(merged), "batch:", batch)
    if args.dry_run:
        for x in fresh[:8]:
            print(" -", x["kind"], x["category"], x["title"][:40])
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("written:", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
