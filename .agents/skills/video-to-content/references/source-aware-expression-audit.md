# 来源感知表达审校

在完整的来源忠实成稿已经形成、章节与配图计划已经完成之后读取本页。这里处理的是 Agent 为载体
新增的表达痕迹，不是再次改写视频创作者。

`source-aware` 的意思是：先判断一句话从哪里来，再判断是否需要调整。来源真实表达拥有优先级；
不能因为一句话形式上像某条“AI 味”规则就命中即修改。

## 目标

清理 Agent 新增的标题、转场、总结和证据边界说明中的模板表达，同时保持：

- 来源结构、人物身份、观点归属和论证顺序；
- 数字、案例、反例、限定、不确定性和专业密度；
- 来源自带的幽默、情绪、反问、排比、比喻和口头特点；
- 已审计的章节映射、图片位置和媒体顺序。

这不是全文去 AI 味，也不是固定公众号文风。审校后文章仍应像原视频，只是 Agent 自己补写的
载体语言更直接、更少模板感。

## 判断顺序

逐个检查标题、summary、headings、开场、转场、证据边界、总结和 ending：

1. **来源归属**：这句话、对照或修辞是否能在 Transcript 或来源结构中找到？
2. **实质作用**：它是否承担事实、限定、人物态度、论证推进或必要的阅读衔接？
3. **Agent 痕迹**：问题是否由 Agent 新增的载体表达造成，而不是来源作者本来的说法？
4. **最小处理**：能否只改解决该问题所需的句子，不顺手润色相邻文字？
5. **回到来源**：修改后是否仍保留原来的信息密度、语气、权重和顺序？

不确定来源归属或实质作用时，保留，并把判断记录为 `retained`。不能为了降低命中数量而删内容。

## 可以检查的规则族

规则只提供观察角度，不授权自动改写。每次修改必须同时满足“Agent 新增或载体适配”与“最小修改”。

### `manufactured_contrast`

Agent 先制造来源没有的误解，再用“不是 A，而是 B”“看似……实际……”等结构翻案。若来源人物
确实在排除误解、比较两面或表达矛盾，保留。

### `empty_signpost`

“一句话总结”“先把话说清”“严谨的写法只能说”等提示语没有新增信息，只是在宣布接下来要说
什么。能直接表达时删掉空转部分；真实的证据等级和不确定性必须保留。

### `repeated_sentence_scaffold`

相邻句连续套用同一骨架，读起来像填表。只调整 Agent 新增的连接方式，不删除事实，也不打乱
来源顺序。步骤、条款、真实排比和人物原话不处理。

### `agent_abstraction`

来源已有数字、时间、对象或案例，Agent 却用“显著提升”“大量”“明显改善”等概括盖住具体
材料。把已有材料恢复到表达位置，不补来源没有的数据。

### `carrier_template`

为了公众号载体凭空增加营销标题、整齐编号、固定结尾、导师口吻或“核心结论”模板。载体只能
改善阅读，不能生成一个新作者。

### `dense_enumeration`

Agent 新增的同义罗列没有实质区分。专业流程、分账项目、法规条目、人物清单和理解论证所需的
案例必须完整保留；顿号数量本身不是修改理由。

### `missing_anaphora`

Agent 新增的段首评论没有说明在评论什么，例如直接用“值得注意的是”“问题在于”起段。补足
必要回指即可，不借机重写整段。

### `translationese_shell`

Agent 新增的前置话题壳、空转连接词或复述句让中文生硬。只有确认不承担范围限定、时间关系或
新结论时才做局部调整。被动句、名词化和长句本身不是问题。

### `decorative_personification`

Agent 把工具、系统或流程包装成理想化导师、秘书或顾问，却没有解释新机制。这通常也违反来源
忠实的“不得新增比喻”边界。来源自带的比喻不得按本条删除。

## 不能作为修改理由

- 句子或段落不够长短交错；
- 使用问句、反问、排比、比喻、冒号或破折号；
- 正文出现“首先、其次”或步骤编号；
- 重复人物全称、使用被动句、名词化或专业长句；
- 一句话“不够口语”“不够像自媒体”；
- 规则扫描命中次数偏高。

这些现象可能属于来源风格、专业文体或真实结构。不得强加“我/你”、短段落、网络梗或情绪化
表达，也不得把专业内容改成统一的固定公众号文风。

## `expression_audit` 合同

在现有 Content audit 中保存一次 Agent 审校结果，不新增业务产品：

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
    "items": []
  }
}
```

`items=[]` 是合法结果，表示实际检查后没有需要修改或特别保留的命中，不得为了填审计而制造改写。

需要记录时，每项使用完整目标文本：

```json
{
  "target": {"field": "block", "block_index": 12},
  "rule": "manufactured_contrast",
  "decision": "revised",
  "origin": "agent_added",
  "before": "审校前该 block 的完整文本",
  "after": "最终 Content 中该 block 的完整文本",
  "reason": "来源没有这层误解，删除 Agent 新增的翻案框架"
}
```

约束：

- `target.field` 只能是 `title`、`summary` 或 `block`；
- `block_index` 必须指向带文本的真实 block；若目标是 `list`，完整文本按 `items` 顺序用换行连接；
- `decision=revised` 时，`origin` 只能是 `agent_added` 或 `carrier_adaptation`，且
  `before != after`；
- `decision=retained` 时通常使用 `origin=source_expression`，且 `before == after`；
- `after` 必须与最终 Content 对应目标完全一致；
- `reason` 说明来源与编辑判断，不能只写“去 AI 味”。

## 最终复核

表达审校完成后，不以“更顺”作为完成信号。重新检查：

1. 开头、中部和结尾的实质信息是否仍在；
2. 专业术语、数字、案例、限定和观点归属是否未被压缩；
3. 标题和总结是否没有增强来源主张；
4. 章节顺序、`material_sections`、图片 block 和 `visual_plan` 是否仍一致；
5. 所有 `expression_audit.items[*].after` 是否等于最终文档文本；
6. `content_validate.valid=true` 后才允许进入微信交接。

方法受到 `larashero3-dotcom/lieflat-less-ai-tone` 的白名单最小修改、信息守恒和反例意识启发；
本项目不引入其运行时依赖，也不采用“形式命中即修改”。
