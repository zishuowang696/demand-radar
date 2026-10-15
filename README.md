# demand-radar

> 爬树莓派 / NVIDIA 生态的**官方 + 高流量论坛**，回答一个问题：**客户最需要什么？**
> By [embedai.com.cn](https://embedai.com.cn)

## 它做什么
自动抓取并排序论坛里「**有人问、没人解**」的信号，输出 `demand.md`：
- **A. 愿意掏钱的需求（💰）**：标题含「求购/外包/预算/for hire/commercial…」→ 加权 ×3（**愿不愿掏钱 = 真伪需求的分水岭**）
- **B. 其他未满足需求**：**新近 + 未回答** / 高浏览低回答
- **C. 社区热议**：高赞、多评论

排序 = **未满足度 × 热度 × 新鲜度**（近期加权，避免老帖霸榜）。

> 说明：论坛标题很少直接说"付钱"，所以 💰 命中偏低；**真正的"掏钱信号"在招聘/接单板**（公司在招=肯为这个能力付钱）——下一步可加这类源。

## 数据源
| 类型 | 来源 |
|---|---|
| 官方论坛 | NVIDIA 开发者论坛（Discourse API）· 树莓派官方论坛（RSS） |
| 问答站 | StackExchange（raspberrypi，取**未回答**） |
| 高流量社区 | Reddit（可选，需 `RADAR_REDDIT=1`；机房 IP 常被拒） |

## 成本（重要）
- **爬取：0 成本**（全走公开 API / RSS）；
- **LLM：默认关闭**。勾选后**每次只调用 1 次**，只喂 Top 40 标题、`max_tokens` 卡死（DeepSeek 上几厘钱）；
- **手动触发**，你想跑才跑。

## 用法
本地：
```bash
pip install -r requirements.txt
python demand_radar.py                        # 全量抓取 + 排名
python demand_radar.py --query voice --query whisper
python demand_radar.py --llm                  # 加 LLM 聚类（需 DEEPSEEK_API_KEY）
```

GitHub 上（**推荐**）：Actions → `demand-radar` → **Run workflow**（可填关键词、勾选 LLM）→ 跑完看 `demand.md` 和自动开的 Issue。

## 环境变量
| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 可选；配了才能用 `--llm` |
| `RADAR_LLM=1` | 等价于 `--llm` |
| `LLM_MAX_TOKENS` | 默认 1200，卡成本 |
| `RADAR_TOP` | 默认 40 |

## 许可
MIT
