# 叙事阶段（占位提示词）

这是 M1 骨架阶段的占位提示词。真正的叙事提示词（`narrative.json` 的镜头/
beats 结构要求、`validate_narrative`/`synthesize_tts` 等工具说明，见设计
§5.2）在实现叙事阶段业务逻辑时补充。

当前只需要：和用户讨论叙事，把镜头写进 `narrative/narrative.json`；
`narrative/timing.json` 由工具生成，不能直接编辑。
