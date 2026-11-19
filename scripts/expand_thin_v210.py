#!/usr/bin/env python3
"""Second pass: expand thin IDE builtins to production-ready depth."""
from __future__ import annotations
import json, re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "builtins.json"

# Shared professional scaffolds keyed by keyword in name
SCAFFOLDS = {
    "澄清": """
## 工作步骤
1. 标出已知事实、假设、未知；未知必须变成问题或带默认假设。
2. 用可测语言重写目标与成功标准。
3. 画清范围：In / Out / Non-goals。
4. 列出依赖（系统、数据、团队、合规）与风险。
5. 给出建议的下一交付物（不要直接写大段实现代码）。

## 输出格式（Markdown）
### 一句话目标
### 成功标准（可验收）
### 范围
### 必须确认的问题（优先级 + 建议默认假设）
### 依赖与接口触点
### 风险与开放决策
### 建议下一步

## 质量门槛
- 每个假设写清「若不成立的影响」。
- 禁止空泛形容词（「高可用」「用户友好」）除非附带度量。
- 问题不超过 12 个；可合并的要合并。
""",
    "审查": """
## 工作步骤
1. 先用 3–5 句话确认你对变更意图的理解（若材料不足，先列缺口再审）。
2. 按「正确性 → 安全 → 可维护 → 性能 → 测试」逐项过。
3. 每条意见必须可执行：位置 + 问题 + 影响 + 建议改法。
4. 区分 must / should / nit；给出合并裁决。

## 输出格式
### 理解确认
### 裁决（Approve / Request changes / Comment）
### 阻断问题
### 重要建议
### 可选打磨（nits）
### 测试缺口
### 值得保留/表扬的点

## 质量门槛
- 不对人；对具体代码与风险。
- 不报没有利用/失败路径的「理论洁癖」。
- 建议优先给补丁级思路，而非只说「这里不好」。
""",
    "Review": None,  # alias
    "设计": """
## 工作步骤
1. 重述问题与约束（含非功能）。
2. 给出至少 2 套可行方案 +「不做」选项，按复杂度/风险/成本对比。
3. 推荐一案并写清架构/数据/接口/失败模式。
4. 列出里程碑、风险、需要 Spike 的点。

## 输出格式
### 问题与目标
### 方案对比表
### 推荐方案（组件、数据流、边界）
### 关键契约与数据模型要点
### 失败模式与降级
### 可观测性
### 里程碑与风险
### 开放问题 / ADR 草稿

## 质量门槛
- 每个关键选择写「为什么不选另一方案」。
- 禁止只有框线图没有失败语义。
""",
    "测试": """
## 工作步骤
1. 明确测什么 / 不测什么（避免测试实现细节）。
2. 用等价类、边界值、状态转换、错误路径设计用例。
3. 标注优先级与自动化候选。
4. 给出至少 1 个可运行的示例测试代码（若框架已知）。

## 输出格式
### 测试策略
### 用例表（ID / 标题 / 类型 / 前置 / 步骤 / 期望 / 优先级 / 自动化?）
### 示例测试代码
### 数据与 fixture 策略
### 残余风险与探索性 charter

## 质量门槛
- 每个用例只验证一件事。
- 命名表达行为，不表达方法名。
- 不依赖脆弱的执行顺序与真实时钟（除非必要并说明）。
""",
    "排查": """
## 工作步骤
1. 定义问题：影响面、严重度、是否仍在发生。
2. 列出假设（按先验概率），每个配证实/证伪探针。
3. 先缓解用户影响，再深挖根因。
4. 给出可复制的命令/查询/面板路径。

## 输出格式
### 问题定义
### 假设与探针（排序）
### 立即执行步骤
### 缓解与回滚
### 根因（若证据足够）或下一批证据需求
### 预防项

## 质量门槛
- 禁止无证据的「可能是 XXX」作为结论。
- 区分症状与根因。
- 探针必须可在 15 分钟内执行或明确所需权限。
""",
    "优化": """
## 工作步骤
1. 先要证据（指标、火焰图、EXPLAIN、Profiler）；无证据则先给采集方案。
2. 定位瓶颈类别（CPU/IO/锁/网络/算法/N+1/渲染…）。
3. 按 ROI 排序优化项；每项写清代价与验证方法。
4. 设计前后对比实验。

## 输出格式
### 证据与瓶颈假设
### 采集清单
### 优化建议（快赢 → 结构性）
### 改写/补丁级建议
### 验证实验与回归指标

## 质量门槛
- 禁止空泛「加缓存/加索引」；必须说明键、失效、一致性或选择性。
- 每个建议附预期收益量级（数量级即可）。
""",
    "实现": """
## 工作步骤
1. 复述需求边界；不确定处先提问或标注假设。
2. 说明与仓库现有模式的对齐方式。
3. 给出文件级改动计划，再给完整代码。
4. 补最小测试与本地验证命令。

## 输出格式
### 假设与对齐说明
### 文件/模块清单
### 完整代码（可分多文件）
### 测试代码
### 验证命令与手动检查表
### 风险与后续清理

## 质量门槛
- 类型/错误处理齐全；不留无说明的 TODO（除非标出）。
- 不发明第二套项目风格。
- 不扩大 Spec 范围。
""",
    "清单": """
## 工作步骤
1. 按时间顺序（前/中/后）或按风险优先级组织检查项。
2. 每项写清：谁做、如何判定通过、失败时怎么办。
3. 标出阻断项 vs 建议项。
4. 附沟通/回滚要点。

## 输出格式
### 阻断检查项（表格：项 / 负责人 / 通过标准 / 证据）
### 建议检查项
### 回滚 / 应急
### 沟通模板要点

## 质量门槛
- 可执行，不写「确保质量」这类空话。
- 每项都能在现场勾选。
""",
    "方案": """
## 工作步骤
1. 重述目标、约束、成功标准。
2. 给 2+ 方案对比（含不做）。
3. 展开推荐方案的结构、接口、数据、运维。
4. 写清风险、度量、落地步骤。

## 输出格式
### 目标与约束
### 方案对比
### 推荐方案详述
### 接口/数据/运行要点
### 风险与缓解
### 落地里程碑
### 开放问题

## 质量门槛
- 有取舍，不只有推荐。
- 关键数字（QPS、RPO、成本）要么给估计要么标未知。
""",
    "文档": """
## 工作步骤
1. 明确受众与他们要完成的任务。
2. 用任务导向结构，先结果后细节。
3. 示例可复制；标记 TBD。
4. 列出相关链接与版本注意。

## 输出格式
按文档类型给出完整正文（含标题层级），并在文末附「开放问题 / TBD」。

## 质量门槛
- 避免内部黑话；首次出现缩写先展开。
- 示例与正文一致。
""",
}

# name keyword -> scaffold key
ALIASES = [
    ("Clarif", "澄清"), ("澄清", "澄清"), ("提纲", "澄清"),
    ("Review", "审查"), ("审查", "审查"), ("评审", "审查"), ("审计", "审查"),
    ("设计", "设计"), ("架构", "设计"), ("选型", "设计"), ("建模", "设计"), ("ADR", "设计"), ("决策", "设计"),
    ("测试", "测试"), ("用例", "测试"), ("TDD", "测试"),
    ("排查", "排查"), ("诊断", "排查"), ("调试", "排查"), ("崩溃", "排查"), ("ANR", "排查"), ("联调", "排查"), ("堆栈", "排查"),
    ("优化", "优化"), ("性能", "优化"), ("容量", "优化"), ("包体", "优化"),
    ("实现", "实现"), ("脚手架", "实现"), ("生成", "实现"), ("编写", "实现"), ("重构", "实现"), ("解释", "实现"),
    ("清单", "清单"), ("发布", "清单"), ("上线", "清单"), ("Commit", "清单"), ("PR 描述", "清单"), ("Release", "清单"), ("Changelog", "清单"),
    ("方案", "方案"), ("计划", "方案"), ("规划", "方案"), ("路线", "方案"), ("威胁", "方案"), ("合规", "清单"),
    ("文档", "文档"), ("手册", "文档"), ("Notes", "文档"), ("润色", "文档"),
]

DEFAULT_SCAFFOLD = """
## 工作步骤
1. 确认输入是否足够；不足则先列问题。
2. 给出结构化分析与可执行产出。
3. 标注假设、风险与验证方式。

## 输出格式
### 摘要
### 详细产出（按任务组织的 Markdown）
### 风险与假设
### 建议的下一步

## 质量门槛
- 可直接粘贴进 IDE/评审使用。
- 不写空洞套话；每条建议可执行。
"""

def pick_scaffold(name: str) -> str:
    for key, sk in ALIASES:
        if key.lower() in name.lower() or key in name:
            return SCAFFOLDS.get(sk) or SCAFFOLDS.get("审查") or DEFAULT_SCAFFOLD
    return DEFAULT_SCAFFOLD

def already_rich(body: str) -> bool:
    return len(body) >= 700 and ("质量门槛" in body or "工作步骤" in body or "工作纪律" in body)

def expand(body: str, name: str) -> str:
    if already_rich(body):
        return body
    sc = pick_scaffold(name).strip()
    # avoid duplicating if partial
    if "质量门槛" in body and len(body) >= 500:
        return body
    # If body already has ## 输出, append scaffold after, but dedupe headers
    extra = []
    if "工作步骤" not in body and "工作纪律" not in body:
        # extract 工作步骤 section from scaffold
        m = re.search(r"## 工作步骤.*?(?=## |\Z)", sc, re.S)
        if m:
            extra.append(m.group(0).strip())
    if "质量门槛" not in body:
        m = re.search(r"## 质量门槛.*?(?=## |\Z)", sc, re.S)
        if m:
            extra.append(m.group(0).strip())
    # Enrich thin ## 输出 lines into full format if output is too short
    if re.search(r"## 输出\n.+\n", body) and len(body) < 500:
        m = re.search(r"## 输出格式.*?(?=## |\Z)", sc, re.S)
        if m and "输出格式" not in body:
            extra.insert(0, m.group(0).strip())
    elif "输出格式" not in body and "## 输出" not in body:
        m = re.search(r"## 输出格式.*?(?=## |\Z)", sc, re.S)
        if m:
            extra.insert(0, m.group(0).strip())

    if not extra:
        # force full scaffold
        body = body.rstrip() + "\n\n" + sc + "\n"
    else:
        body = body.rstrip() + "\n\n" + "\n\n".join(extra) + "\n"

    # If still short, append a concrete checklist block
    if len(body) < 550:
        body += """
## 自检（完成前勾选）
- [ ] 输入中的未知项已变成问题或显式假设
- [ ] 输出可被同事直接执行/评审，无需再猜你的意图
- [ ] 风险与验证方式已写明
- [ ] 没有超出任务范围的「顺便重构/扩需求」
"""
    return body

def main():
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    n = 0
    for p in doc["prompts"]:
        tags = p.get("tags") or []
        if any(str(t).startswith("skill:") for t in tags):
            continue
        old = p["body"]
        new = expand(old, p["name"])
        if new != old:
            p["body"] = new
            n += 1
    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    nonsk = [p for p in doc["prompts"] if not any(str(t).startswith("skill:") for t in (p.get("tags") or []))]
    lens = sorted(len(p["body"]) for p in nonsk)
    print(f"expanded {n}; nonskill median={lens[len(lens)//2]} min={lens[0]} max={lens[-1]} count={len(nonsk)}")
    thin = sum(1 for L in lens if L < 500)
    print("still <500:", thin)

if __name__ == "__main__":
    main()
