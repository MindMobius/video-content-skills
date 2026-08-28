# 来源感知表达审校设计

- 日期：2026-08-28
- 状态：已批准
- 分支：`codex/source-aware-expression-audit`

## 1. 背景

`source_faithful_full` 已经约束 Agent 保留视频的结构、人物、专业密度、案例、限定和画面，
也能阻止逐条字幕机械直贴。但真实文章仍可能出现另一类问题：事实与细节都在，Agent 为了组织
公众号载体而新增的标题、转场、总结和证据边界说明带有重复模板，例如反复使用“不是 A，而是
B”“先把话说清”“严谨的写法只能说”或空转提示语。

这不是来源内容错误，也不应通过统一“去 AI 味”重写解决。来源本身可能真实使用反问、排比、
破折号、并列项目或对照表达；机械清理会再次损失作者声音和专业信息。

## 2. 方案比较

### 2.1 不采用：直接引入外部全文改写 Skill

优点是接入快，缺点是把外部规则变成新的作者，容易修改来源真实表达，并增加运行时依赖和版本
漂移。它也无法利用 Transcript、章节映射和来源证据判断一句话究竟来自视频还是 Agent。

### 2.2 不采用：只在提示词里补一句“少一点 AI 味”

提示词没有完成证据。真实输出再次出现模板表达时，系统仍可能写入 `status=passed`，无法区分
“Agent 已审校”与“Agent 忘记审校”。

### 2.3 采用：现有 Content 内的来源感知表达审校

在来源忠实成稿和完整性/配图审计之后，增加一次 Agent 语义审校；结果写入现有 Content audit，
由验证器检查审校合同。它不是新的业务产品，也不是新的独立 Skill。

```text
Transcript
-> 来源忠实书面化
-> 章节与配图审计
-> 来源感知表达审校
-> 再次来源忠实复核
-> content_validate
-> 可选微信交接
```

## 3. 判断边界

表达审校只处理 Agent 或载体适配新增的文字，重点覆盖：

- 标题、摘要和小标题；
- 开场、转场、总结和结尾；
- 证据边界、可信等级和“不应如何理解”的说明；
- Agent 新增的模板对照、空转路标、重复句法和抽象概括。

来源真实表达优先。以下现象不能单独成为修改理由：

- 来源人物真实使用的“不是……而是……”、反问、排比或比喻；
- 专业流程、法律条目、分账项目和其他必要并列；
- 来源已有的破折号、冒号、长句、问句或编号步骤；
- 为完整保留数据、案例、限定和人物关系所需的重复。

冲突时，来源忠实高于“更像人写的”。不确定来源归属时保留原文，并在审计中记录 `retained`。

## 4. Agent 与程序分工

### Agent 判断

- 某个表达来自 Transcript，还是 Agent 后来补写；
- 对照是否真实存在，还是先制造误解再翻案；
- 罗列是必要专业信息，还是模板化堆砌；
- 修改是否只触及解决问题所需的最小范围；
- 修改后是否仍保留来源的专业密度、语气和论证推进。

### 程序验收

- `source_faithful_full` Content 是否包含通过的 `expression_audit`；
- 审校是否由 Agent 完成并声明 `source_aware_minimal` 策略；
- 标题摘要、标题层级、转场、证据边界和结尾是否进入检查范围；
- 每项 `revised` 或 `retained` 决策是否指向真实的最终文档文本；
- `revised` 是否只用于 `agent_added` 或 `carrier_adaptation`，不得把
  `source_expression` 伪装成可随意重写的内容；
- 章节映射、图片位置、媒体顺序、数字与来源忠实仍由现有 Content 合同继续约束。

程序不自动扫描所谓 AI 味，不计算风格分数，也不根据正则自行改文。

## 5. Content audit 合同

`source_faithful_full` 的 audit 增加：

```json
{
  "expression_audit": {
    "status": "passed",
    "reviewed_by": "agent",
    "policy": "source_aware_minimal",
    "reviewed_targets": [
      "title_summary",
      "headings",
      "transitions",
      "evidence_boundaries",
      "ending",
      "material_details"
    ],
    "checks": {
      "source_expression_priority": true,
      "information_density_preserved": true,
      "structure_and_media_preserved": true,
      "final_source_fidelity_rechecked": true
    },
    "items": [
      {
        "target": {"field": "block", "block_index": 12},
        "rule": "manufactured_contrast",
        "decision": "revised",
        "origin": "agent_added",
        "before": "原文完整文本",
        "after": "最终文档完整文本",
        "reason": "该对照由 Agent 新增，来源没有先立误解再翻案"
      }
    ]
  }
}
```

`items` 可以为空，表示检查后没有需要记录的命中。若有项目：

- `target.field` 为 `title`、`summary` 或 `block`；
- `block` 必须给出有效 `block_index`，且指向有文本的文档 block；
- `after` 必须等于最终目标文本；
- `revised` 要求 `before != after`，且来源为 `agent_added` 或
  `carrier_adaptation`；
- `retained` 要求 `before == after`，用于记录虽然形式命中但因来源表达或实质信息而保留；
- `reason` 必须说明具体判断，不能只写“去 AI 味”。

稳定规则 ID 首批限定为：

- `manufactured_contrast`
- `empty_signpost`
- `repeated_sentence_scaffold`
- `agent_abstraction`
- `carrier_template`
- `dense_enumeration`
- `missing_anaphora`
- `translationese_shell`
- `decorative_personification`

## 6. Skill 与文档

在 `video-to-content` 下新增按需 reference，入口 Skill 只增加读取条件和主流程要求；
`watch-later-to-wechat` 只要求表达审校通过，不复制规则。README、AGENTS、architecture 和 Skill
维护文档同步说明该闸门的角色。

规则设计参考 `larashero3-dotcom/lieflat-less-ai-tone` 的白名单最小修改、信息守恒和反例意识，
但不复制为运行时依赖，也不采用“命中即修改”。来源忠实始终拥有更高优先级。

## 7. 验证

回归测试至少证明：

1. 缺少 `expression_audit` 的 Watch Later Content 不能进入微信交接；
2. no-op 审校可以通过，不强迫无意义改写；
3. `revised` 项不能声明来源为 `source_expression`；
4. 审计的 `after` 必须与最终文档目标完全一致；
5. Skill 明确要求只处理 Agent 新增表达，并保留来源真实对照和必要专业罗列；
6. 现有章节、图片、字幕直贴和微信边界测试继续通过。
