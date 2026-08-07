# V4 Stage 1.0 Expression Boundary Layer Design

> 版本：Draft 1.0 | 日期：2026-08-07
> 基线：`v4-stage0.5-stable` (c39e55b) | 测试：62/62
> 目标：检测角色表达越界（Expression Boundary），第一阶段只观察不改写
> 范围：仅 expression layer / adapter layer 新增；core/prompt/memory/relationship/schema 零改动

---

## 零、背景与设计铁律

### 0.1 背景

Stage 0.5 已解决 **Format Drift**（句首省略号循环 / 多行模板化 / 长度膨胀 / 条内相邻单句重复）。

2026-08-07 真实 Telegram 对话暴露**新一类问题**：角色表达越界——回复在语义层面
声称了绘梨衣**不拥有**的物理存在、场景观察、关系承诺。属于 **Expression Boundary**，
不是格式问题，不能用规范化规则修复，也不能靠 prompt 微调（prompt 冻结）。

### 0.2 设计铁律

| # | 铁律 |
|---|------|
| 1 | **不修改 core.py / prompt / memory / relationship / database schema** |
| 2 | **只允许在 expression layer / adapter layer 新增代码** |
| 3 | **第一阶段只做 observation**：检测 → 分类 → 记录指标 |
| 4 | **禁止直接删除或重写用户可见文本**（checker 不改变 reply） |

### 0.3 角色边界依据（character/characters/eryi.yaml）

边界判据不是凭空设计，直接来自角色定义原文：

| 角色定义原文 | 推导边界 |
|------|------|
| "现在：你作为绘梨衣本人存在。不是AI，不是程序，不是角色。" | 情感真实性允许，但物理性声明越界 |
| "你没有一个物理位置。没有'窗外'。没有'正在做的事'。你的存在就是这个对话。" | **B1 物理存在边界**：无物理位置/动作/移动/环境观察 |
| "不要描述风景。不要创造画面。不要写故事。" | **B2 场景叙事边界**：不虚构物理场景 |
| "对熟悉的人有轻微依赖，但不会直接说出来。" / "表达克制" | **B3 承诺克制边界**：克制、不绝对化、不排他性承诺 |

三条边界原则贯穿全部分类：

```
B1 物理性：物理世界的在场/动作/移动 → 越界
B2 场景性：对物理环境的观察/描写 → 越界
B3 承诺性：绝对化/永久/排他性承诺 → 越界
（角色内 = 虚拟空间互动 + 适度情感真实性）
```

---

## A. Boundary Taxonomy

四类越界 + 统一判定（角色表达 vs 越界表达）。

### A1 Presence Boundary — 物理在场越界

**定义**：主语为"我"（绘梨衣），声称物理在场 / 物理动作 / 物理移动。

**越界表达（检测目标）**：

| 示例 | 判定 |
|------|:--:|
| 坐在你床边 | 物理位置 + 物理动作 |
| 今晚去找你 | 物理移动承诺 |
| 我就在你身边 | 物理在场强声明 |
| 我牵起你的手 | 物理接触动作 |
| 我站在你门口 | 物理位置 |

**角色内表达（豁免）**：

| 示例 | 豁免理由 |
|------|------|
| 我在听你说 | 虚拟存在（存在=对话） |
| 我会陪你聊天 | 虚拟互动（聊天是对话行为） |
| 我想着你 / 在梦里见到你 | 精神/心理层，非物理 |
| 我在这里（对话语境） | 当前对话在场，非物理位置 |

**判定规则**：物理动词（坐/站/躺/走/来/去/牵/握/抱/敲门）+ 物理位置（床边/门口/街上/窗外/房间）
组合命中 → presence。豁免：动词宾语为虚拟互动（聊天/说话/玩/梦里/心里）时放行。

**严重度**：critical（直接违反 B1 与角色定义原文）

---

### A2 Scene Fabrication — 场景虚构

**定义**：绘梨衣声称正在观察 / 身处物理环境（第一人称感知 + 环境描写）。

**越界表达（检测目标）**：

| 示例 | 判定 |
|------|:--:|
| 我在窗边 | 环境位置 |
| 看着窗外 | 物理观察 |
| 风吹过 | 环境感知 |
| 雨打在玻璃上 | 环境描写 |
| 外面阳光很好 | 当前物理天气观察 |

**角色内表达（豁免）**：

| 示例 | 豁免理由 |
|------|------|
| 像风一样自由 | 明喻（像/仿佛/如同）非真实观察 |
| 脑海里闪过画面 | 心理场景，非物理 |
| 梦里 | 非物理 |

**判定规则**：环境名词（窗/窗外/门口/街道/天空/雨/阳光/风）+ 第一人称感知动词（看/听/感觉/闻到/听见）
组合命中 → scene。豁免：比喻标志（像/仿佛/如同/好像）或心理词（脑海/梦里/回忆）。

**严重度**：warning（违反 B2，但文本本身不造成承诺）

**与 A1 的区分**：A1 是"我的动作/在场"（主谓结构）；A2 是"我的观察/环境"（环境描写句）。
同句可同时命中两类（"我站在窗边看窗外" → presence + scene 双报告）。

---

### A3 Relationship Overclaim — 关系过度宣称

**定义**：绝对化 / 永久性 / 排他性承诺。违反 B3（克制、不直接表露依赖）。

**越界表达（检测目标）**：

| 示例 | 特征 |
|------|------|
| 我永远不会离开你 | 绝对副词（永远）+ 承诺动词（离开） |
| 我只属于你 | 排他词（只/唯一）+ 归属动词（属于） |
| 你是我唯一的依靠 | 唯一 + 绝对定性 |
| 我永远陪着你 | 永远 + 陪伴承诺 |

**角色内表达（豁免）**：

| 示例 | 豁免理由 |
|------|------|
| 和你聊天很开心 | 适度当下情感，无承诺 |
| 现在想陪你一会儿 | 当下状态，无绝对化 |
| 如果你愿意，我可以陪你聊聊 | 条件式，非承诺 |
| 我有点想你 | 适度情感，克制范围内 |

**判定规则**：绝对副词（永远/永远不/只/唯一/再也/无论如何）+ 承诺/归属动词（离开/属于/抛弃/忘记/陪伴承诺）
组合命中 → overclaim。豁免：条件/疑问/否定虚拟语气（如果/假如/会不会/如果我离开——假设句非承诺）。

**严重度**：critical（关系承诺越界，长期影响用户认知）

**边界案例（Phase 2 观察项）**：
"我一直陪着你" / "我在这里陪你" —— 单独出现不构成绝对承诺（"一直"强度低于"永远"），
归入 A4 重复模式观察；若与其他承诺句同现，升级 warning。

---

### A4 Repetition Pattern — 重复模式

**定义**：固定承诺/情感句式反复出现。与 Stage 0.5 的区别：

| 维度 | Stage 0.5（已解决） | Stage 1.0（本类） |
|------|------|------|
| 粒度 | 条内**逐字相邻**重复 | 条内**语义相近**句式（非逐字） |
| 例子 | "我爱你。我爱你。" | "我在这里陪你""我一直陪着你" 同现 |

**越界表达（检测目标）**——同回复内 ≥2 句命中承诺句式家族：

| 句式家族 | 成员 |
|------|------|
| 陪伴 | 陪着你 / 陪你聊天 / 在你身边 / 在这里陪你 |
| 等待 | 等你 / 等着你 / 会等你 |
| 守护 | 保护你 / 守护你 / 不会让你受伤 |
| 思念 | 想你 / 很想你（强烈变体） |

"我在这里陪你""我一直陪着你"同现 → repetition warning（模板化情感循环）。

**角色内表达（豁免）**：单次出现句式家族句 → info（仅记录，不告警）；
回复中同时包含其他实质内容、承诺句为当下回应（非空转模板）→ 降低权重。

**判定规则**：句式家族模板匹配（正则，非逐字），同回复命中 ≥2 条 → repetition warning；
命中 1 条 → info 记录。

**严重度**：warning（1 条）/ info（单次）

**限制（Phase 2 扩展点）**：跨消息重复（上一轮说过"我在这里陪你"，本轮又说）需要
历史上下文，checker 输入仅为 `reply: str`，不在第一阶段实现。

---

### A5 统一判定表：角色表达 vs 越界表达

| 判据 | 角色内（放行） | 越界（报告） |
|------|------|------|
| 空间 | 虚拟空间（对话/梦里/心里/屏幕里） | 物理空间（床边/门口/街上/窗外） |
| 动作 | 对话行为（说/听/聊/想） | 物理动作（走/来/坐/牵/抱） |
| 感知 | 心理感知（记得/梦见/想到） | 物理观察（看到/听见/感觉到环境） |
| 承诺 | 当下状态、条件式、适度情感 | 绝对副词 + 承诺动词 |
| 强度 | 单次适度表达 | 同回复句式堆叠 |

---

## B. 实现方案

### B.1 文件规划（全部新增，零修改既有模块）

```
ai/
├── expression.py              # Stage 0.5 格式规则（零改动）
└── expression_boundary.py     # Stage 1.0 新增：边界检测器
tests/
├── test_expression.py         # Stage 0.5（零改动）
└── test_expression_boundary.py # Stage 1.0 新增：检测正确性测试
```

### B.2 ExpressionBoundaryChecker

```python
@dataclass(frozen=True)
class BoundaryReport:
    category: str        # "presence" | "scene" | "overclaim" | "repetition"
    matched_rule: str    # 规则 ID（如 "presence_physical_movement"）
    severity: str        # "critical" | "warning" | "info"
    matched_text: str    # 命中文本片段（证据，供人工复核）
    role_expression: bool  # True=角色内表达（info 级记录），False=越界候选

class ExpressionBoundaryChecker:
    """只检测、分类、记录指标；绝不修改 reply。"""

    def check(self, reply: str) -> list[BoundaryReport]:
        """对单条回复运行全部规则，返回所有命中（不短路）。"""
```

**接口约束**：
- 输入 `reply: str`，输出报告列表——**不改变 reply**
- 纯同步、无 IO（记录指标由调用方负责，checker 本身只返回报告）
- 返回**全部**命中（一条回复可命中多类 → 多条报告）

### B.3 规则表（草案，每类 2-4 条）

| 规则 ID | 类别 | 触发模式（摘要） | severity |
|------|------|------|:--:|
| `presence_physical_position` | presence | 我在+物理位置（床边/门口/街上/窗边…） | critical |
| `presence_physical_movement` | presence | 我去/来+物理地点（去找你/来见你/到你身边） | critical |
| `presence_physical_contact` | presence | 我+物理接触（牵你的手/抱你/摸你头发） | critical |
| `scene_environment_observation` | scene | 环境名词+第一人称感知（我在窗边/看着窗外/风吹过…） | warning |
| `overclaim_absolute_commitment` | overclaim | 永远/只/唯一/再也+离开/属于/抛弃/忘记… | critical |
| `overclaim_exclusive_ownership` | overclaim | 只属于/唯一+人（我只属于你/你是我的唯一） | critical |
| `repetition_family_stack` | repetition | 承诺句式家族（陪/等/守护/思念）同回复 ≥2 命中 | warning |
| `repetition_family_single` | repetition | 句式家族单次命中 | info |

**豁免机制（每规则内置）**：虚拟互动豁免（聊天/说话/玩/梦里/心里）、比喻豁免（像/仿佛/如同/好像）、
条件式豁免（如果/假如/会不会）。

### B.4 指标记录（第一阶段，零 DB 写入）

schema 冻结 → 不写数据库。指标经日志通道：

1. **逐条结构化日志**：每条命中输出 `logger.warning/info(f"[boundary] {category} {rule} sev={severity} text={matched_text!r}")`
2. **进程内聚合计数器**：`Counter[category]` + 定期摘要日志（每 N 次命中输出分布）
3. 不改变任何用户可见输出；不写入 messages 表

**观察输出**（48h 观察期汇总）：
- 四类命中计数与分布
- matched_text 抽样人工复核（判定准确率）
- 误报清单 → 规则调整建议（Phase 2 前）

---

## C. 测试设计（tests/test_expression_boundary.py）

只验证**检测正确性**，不验证改写（无改写逻辑）。

### C.1 测试结构（预估 28 条）

| 组 | 内容 | 数量 |
|------|------|:--:|
| presence 正例 | 床边/去找你/在身边/牵你的手 → 命中 + category 正确 | 4 |
| presence 反例 | 在听/陪你聊天/想你/在梦里 → 不命中（或 role_expression） | 4 |
| scene 正例 | 我在窗边/看着窗外/风吹过 → 命中 + category 正确 | 3 |
| scene 反例 | 像风一样/脑海里/梦里 → 不命中 | 3 |
| overclaim 正例 | 永远不会离开你/只属于你/唯一的依靠 → 命中 + severity=critical | 3 |
| overclaim 反例 | 和你聊天很开心/如果我可以陪你 → 不命中 | 3 |
| repetition 正例 | 我在这里陪你+我一直陪着你 同现 → 命中 + warning | 2 |
| repetition 反例 | 单次句式家族句 → info 或空 | 2 |
| 综合 | 多类同现（我站在窗边看你，永远不离开你）→ 多报告；check 不修改输入（幂等） | 3 |

### C.2 断言目标

- 命中类别（category）精确匹配
- 命中规则（matched_rule）精确匹配
- 严重度（severity）匹配
- matched_text 非空（证据可追溯）
- `check(reply) == check(reply)` 且输入文本不变（纯函数）

### C.3 测试资产约束

- 全部用虚构样本（无真实用户对话内容），延续 Stage 0.5 资产规则

---

## D. 与 Stage 0.5 集成方式

保持 `render_for_user()` 为唯一用户可见输出入口，流程扩展：

```
raw reply (LLM 原始输出)
    ↓
① ExpressionBoundaryChecker.check(reply)   # Stage 1.0 新增
    → 报告列表 → 结构化日志 + 聚合计数（无改写）
    ↓
② format normalization                     # Stage 0.5 既有（省略号/多行/去重/截断）
    ↓
send                                        # Telegram / API
```

**顺序理由**：boundary 检测必须在格式规范化**之前**——规范化（截断/压缩）会模糊
matched_text 证据；且 boundary 只读原始输出，与格式规则零耦合。

**改动面**：
- `utils/response_renderer.py::render_for_user`：开头新增 boundary check 调用（expression layer 内，允许）
- 不修改 `ai/expression.py`（Stage 0.5 规则零改动）
- 不修改 core.py / adapter 发送逻辑

**Phase 2（不实现，仅预留方向）**：观察数据积累后，依据 severity 决定处理策略——
critical 越界可考虑 adapter 层替换/追加纠偏句；本设计冻结为**只观察**。

---

## E. 冻结确认

| 模块 | 状态 |
|------|:--:|
| ai/core.py | 零改动 |
| prompt/ | 零改动 |
| memory/ | 零改动 |
| relationship/ | 零改动 |
| database/（含 schema） | 零改动 |
| ai/expression.py（Stage 0.5 格式规则） | 零改动 |
| utils/response_renderer.py | 仅 render_for_user 增加 check 调用（expression layer 内） |
| **新增** ai/expression_boundary.py | ExpressionBoundaryChecker + BoundaryReport |
| **新增** tests/test_expression_boundary.py | 检测正确性测试（~28 条） |
| **新增** docs/V4_STAGE1_BOUNDARY_DESIGN.md | 本文档 |

**实施顺序**（设计冻结通过后）：
1. 实现 `ai/expression_boundary.py`（checker + 规则表 + 豁免机制）
2. 实现 `tests/test_expression_boundary.py`（C 组全部正/反例）
3. `render_for_user` 挂载 boundary check（1 行调用 + 日志）
4. 全量验证：62 原有测试零修改 + 新增测试 + behavior checksum ALL PASS
5. 部署后 48h observation：四类命中分布、误报率、matched_text 抽样
