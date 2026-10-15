#!/usr/bin/env python3
"""demand-radar — 爬树莓派 / NVIDIA 生态的官方 + 高流量论坛，找「客户最需要什么」。

数据源：
  官方论坛     NVIDIA 开发者论坛(Discourse) · 树莓派官方论坛(RSS)
  问答站       StackExchange(raspberrypi)
  高流量社区   Reddit: r/raspberry_pi · r/jetson  （社区热度/热议）

信号：
  A 未满足需求：高浏览、低回答 / 未回答（有人问、没人解）→ 最像"客户需要但没人做好"
  B 社区热议：高赞、多评论（大家最关心的话题）
排序：未满足度 × 热度 × **新鲜度**（近期加权，避免老帖霸榜）。

用法：
  python demand_radar.py                 # 全量抓取 + 排名 + 生成 demand.md
  python demand_radar.py --query voice   # 按关键词定向挖
  DEEPSEEK_API_KEY=... python demand_radar.py --llm   # 额外用模型聚类成"需求主题"
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "demand-radar/0.1 (+https://github.com/zishuowang696/demand-radar)"
NVIDIA = "https://forums.developer.nvidia.com"
RPI_FEED = "https://forums.raspberrypi.com/app.php/feed"
SE = "https://api.stackexchange.com/2.3"
REDDITS = ["raspberry_pi", "jetson"]
DEFAULT_QUERIES = ["voice", "speech", "wake word", "voice assistant", "whisper", "asr"]
NOW = time.time()

# 付费意愿信号：出现这些词 = 有人**准备花钱**（求购/外包/预算/商业/支持雇佣）
PAY_RE = re.compile(
    r"willing to pay|paid|for hire|hire (someone|a|an)|\bbudget\b|quote|vendor|"
    r"commercial|enterprise|for production|production[- ]ready|production environment|"
    r"consultant|outsourc|for work|custom (solution|build|development|board)|"
    r"paid support|\bsla\b|licen[cs]e|"
    r"付费|有偿|外包|定制|商用|生产环境|咨询|求购|找人做|报价|预算|接单",
    re.I,
)


def get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _days(iso: str) -> float:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return max(0.0, (NOW - time.mktime(time.strptime(iso[:19], fmt))) / 86400)
        except Exception:
            continue
    return 9999.0


def _recency(days: float) -> float:
    return round(1.0 / (1.0 + days / 365.0), 3)


# ------------------------------------------------------------------ sources

def nvidia_search(term: str) -> list[dict]:
    q = urllib.parse.quote(f"{term} order:latest")
    data = json.loads(get(f"{NVIDIA}/search.json?q={q}"))
    out = []
    for t in data.get("topics", []):
        title = t.get("title", "")
        if term.lower() not in title.lower():
            continue
        out.append({"source": "nvidia", "term": term, "title": title,
                    "url": f"{NVIDIA}/t/{t.get('slug', 'topic')}/{t['id']}",
                    "views": 0, "answers": max(0, t.get("posts_count", 1) - 1),
                    "created": (t.get("created_at") or "")[:10]})
    return out


def nvidia_latest(pages: int = 2) -> list[dict]:
    out = []
    for p in range(pages):
        data = json.loads(get(f"{NVIDIA}/latest.json?page={p}"))
        for t in data.get("topic_list", {}).get("topics", []):
            out.append({"source": "nvidia", "term": "", "title": t["title"],
                        "url": f"{NVIDIA}/t/{t.get('slug', 'topic')}/{t['id']}",
                        "views": t.get("views", 0), "answers": max(0, t.get("posts_count", 1) - 1),
                        "created": (t.get("created_at") or "")[:10]})
        time.sleep(1)
    return out


def se_raspberrypi(term: str | None = None, pages: int = 1) -> list[dict]:
    out = []
    for p in range(1, pages + 1):
        if term:
            path = f"/search/advanced?order=desc&sort=votes&q={urllib.parse.quote(term)}&site=raspberrypi&pagesize=50&page={p}"
        else:
            # 近期的「未回答」（无点赞/无采纳）→ 更像真实、未被满足的需求
            path = f"/questions/unanswered?order=desc&sort=creation&site=raspberrypi&pagesize=100&page={p}"
        data = json.loads(get(SE + path))
        for q in data.get("items", []):
            if term and term.lower() not in q["title"].lower():
                continue
            out.append({"source": "raspberrypi(SE)", "term": term or "", "title": q["title"], "url": q["link"],
                        "views": q.get("view_count", 0), "answers": q.get("answer_count", 0),
                        "created": time.strftime("%Y-%m-%d", time.gmtime(q.get("creation_date", 0)))})
        time.sleep(1)
    return out


def rpi_feed() -> list[dict]:
    root = ET.fromstring(get(RPI_FEED))
    out = []
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = link = ""
        for c in it:
            n = c.tag.split("}")[-1]
            if n == "title":
                title = (c.text or "").strip()
            elif n == "link":
                link = c.get("href") or (c.text or "").strip()
        if title and link:
            out.append({"source": "raspberrypi", "term": "", "title": title, "url": link,
                        "views": 0, "answers": 0, "created": ""})
    return out


def reddit_top(sub: str, period: str = "month", limit: int = 50) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/top.json?t={period}&limit={limit}"
    data = json.loads(get(url))
    out = []
    for ch in data.get("data", {}).get("children", []):
        d = ch["data"]
        out.append({"source": f"r/{sub}", "term": "", "title": d["title"],
                    "url": "https://www.reddit.com" + d["permalink"],
                    "views": d.get("ups", 0), "answers": d.get("num_comments", 0),
                    "created": time.strftime("%Y-%m-%d", time.gmtime(d.get("created_utc", 0))),
                    "kind": "community"})
    return out


# ------------------------------------------------------------------ scoring

def score(it: dict) -> float:
    v, a, days = it["views"], it["answers"], _days(it["created"])
    if it.get("kind") == "community":       # Reddit：热度 = 赞 + 评论
        base = v + a * 2
    elif v:                                  # SE：浏览 / (回答+1)
        base = v / (a + 1)
    else:                                    # 无浏览数据：未回答=强信号
        base = 500 if a == 0 else 20 / (a + 1)
    if it.get("pay"):                        # 有人准备掏钱 = 真需求，加权
        base *= 3
    return round(base * _recency(days), 1)


def collect(queries: list[str] | None) -> tuple[list[dict], list[dict]]:
    need, community = [], []
    jobs = []
    if queries:
        for t in queries:
            jobs += [lambda t=t: nvidia_search(t), lambda t=t: se_raspberrypi(t)]
    else:
        jobs += [nvidia_latest, se_raspberrypi, rpi_feed]
    # 注：Reddit 从机房 IP 常被拒（需 OAuth）；默认不启用，需要时再打开 REDDITS
    if os.getenv("RADAR_REDDIT") == "1":
        jobs += [lambda s=s: reddit_top(s) for s in REDDITS]

    for fn in jobs:
        try:
            for it in fn():
                (community if it.get("kind") == "community" else need).append(it)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 源失败: {e}")

    def dedup_sort(items):
        seen, out = set(), []
        for it in items:
            k = it["url"].split("?")[0]
            if k not in seen:
                seen.add(k)
                it["pay"] = bool(PAY_RE.search(it["title"]))
                it["score"] = score(it)
                out.append(it)
        return sorted(out, key=lambda x: x["score"], reverse=True)

    return dedup_sort(need), dedup_sort(community)


# ------------------------------------------------------------------ LLM

def llm_cluster(items: list[dict], focus: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
                    api_key=os.environ["DEEPSEEK_API_KEY"])
    lines = "\n".join(f"- [{i['source']}] {i['title'][:120]}" for i in items[:40])
    prompt = (
        f"方向：{focus or '树莓派 / NVIDIA(Jetson) 生态'}\n"
        "下面是这些论坛里「未回答 / 高浏览低回答 / 热门」的帖子标题。\n"
        "目标：**找出真实、且有商业价值的需求**；评估者是一个**懂嵌入式+系统+AI Agent 的工程师**。\n"
        "请输出：\n"
        "1) **需求主题**（5-8 个），每个写清：主题名 / 典型问题 / 谁需要 / "
        "**难点**（技术上到底难在哪）/ **这位工程师能不能做**（能/部分/不能，给理由）/ 是否可能付费；\n"
        "2) **优先级**：最该先做的 1-2 个 + 理由；\n"
        "3) **值得回答的帖子**：挑 3-5 个「认真回答就能建立声誉、带外链」的问题（给出标题）；\n"
        "4) **噪音**：哪些与商业无关（纯接线求助、学生作业等）。\n"
        "用中文，务实，不要空话。\n\n" + lines
    )
    r = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1200")),  # 卡死成本
    )
    return r.choices[0].message.content or ""


# ------------------------------------------------------------------ output

def _table(items, rows):
    lines = ["| 分 | 来源 | 需求 | 热/浏览 | 回答 | 日期 |", "|---|---|---|---|---|---|"]
    for it in items[:rows]:
        t = it["title"].replace("|", "\\|")
        mark = "💰 " if it.get("pay") else ""
        lines.append(f"| {it['score']} | {it['source']} | {mark}[{t}]({it['url']}) | {it['views']} | {it['answers']} | {it['created']} |")
    return lines


def write_report(need, community, themes, focus) -> None:
    pay = [x for x in need if x.get("pay")]
    rest = [x for x in need if not x.get("pay")]
    L = [f"# 需求雷达：客户最需要什么（{focus or '树莓派 / NVIDIA 生态'}）", "",
         f"生成时间：{datetime.datetime.utcnow():%Y-%m-%d %H:%M} UTC · "
         f"未满足 {len(need)} 条（其中 💰付费意愿 {len(pay)}）· 热议 {len(community)} 条", "",
         "> 排序 = 未满足度 × 热度 × 新鲜度；**💰 = 标题含「求购/外包/预算/for hire/commercial…」**，加权 ×3（愿意掏钱的才是真需求）。", ""]
    if themes:
        L += ["## 结论（LLM 聚类）", "", themes, "", "---", ""]
    L += ["## A. 愿意掏钱的需求（💰 最强信号）", ""]
    L += _table(pay, 20) if pay else ["（本轮无 💰 信号；可换关键词或看 B/C）"]
    L += ["", "## B. 其他未满足需求（高浏览低回答 / 未回答）", ""] + _table(rest, 20)
    L += ["", "## C. 社区热议（高赞 / 多评论）", ""] + _table(community, 15)
    with open("demand.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append", default=[])
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--top", type=int, default=int(os.getenv("RADAR_TOP", "40")))
    args = ap.parse_args()

    queries = args.query or None
    focus = " / ".join(queries) if queries else ""
    need, community = collect(queries)
    print(f"未满足 {len(need)} 条 · 热议 {len(community)} 条")

    themes = ""
    want_llm = args.llm or os.getenv("RADAR_LLM") == "1"
    if want_llm and os.getenv("DEEPSEEK_API_KEY"):
        try:
            themes = llm_cluster((need + community)[: args.top], focus)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] LLM 失败: {e}")
    write_report(need, community, themes, focus)
    print("写好 demand.md")


if __name__ == "__main__":
    main()
