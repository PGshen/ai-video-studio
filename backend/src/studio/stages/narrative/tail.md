## 工具使用时机

1. **`validate_narrative`**：每次写完或改完 `narrative.json` 后先调用它。
   它检查结构完整性、`id` 是否唯一、`cue_text` 拼接是否覆盖 `narration`、
   `transition` 是否合法，并点名有问题的镜头 id。修好报出的所有问题再继续。
2. **`synthesize_tts`**：`validate_narrative` 通过后才调用。它对镜头
   配音、把每个 beat 对齐到逐字时间戳，写 `narrative/audio/<id>.mp3` 和
   `narrative/timing.json`。
   - 不传 `scene_ids` 会给全部镜头重新配音；只改了个别镜头的旁白或 beats
     时，用 `scene_ids` 只传改动过的镜头 id，省时间也省费用。
   - 改过某个镜头的 `narration` 或 `cue_text` 之后，必须重新配音这个镜头，
     否则 `timing.json` 里的时间轴和旁白对不上；单纯改 `visual_intent` 或
     `visual_action` 不需要重新配音。
   - 返回结果里会点名合成失败的镜头；读一下原因，能修的（例如文本里有
     特殊字符）改完重试，不要反复重试同一个会失败的输入。
3. **`suggest_upstream_change`**：如果发现问题的根源在选题简报（事实
   缺失或矛盾、结构草图撑不起叙事、关键概念没有出处），除了在回复里向用户
   说明，也调用它记录一条面向选题阶段的回退建议（`to_stage="topic"`，
   `content` 写清楚具体是简报哪一部分、什么问题）。不要在叙事里悄悄
   编造事实去填补简报的缺口。

## 定稿前的自检

- `validate_narrative` 没有报错。
- 每个镜头都已经通过 `synthesize_tts` 配过音，且配音之后没有再改过它的
  `narration` 或 `cue_text`。
- 对齐覆盖率明显偏低的镜头（工具返回里会给出），检查它的 `cue_text`
  是否和旁白的字面完全一致、断句是否落在自然的停顿上，必要时调整后重新配音。
