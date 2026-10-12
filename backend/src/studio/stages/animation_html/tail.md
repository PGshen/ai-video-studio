## 工作流（按这个顺序，控制成本）

1. 先读 `style/STYLE.md` 和它指向的风格文件、金样本。
2. 在 `animation/lib/` 里建全片的基底：配色、缓动、常用形状、文字辅助。后面的镜头都复用它。
3. **按镜头顺序逐个做**：写 `animation/scenes/<id>.js` → 调用 `validate_scenes_html`（传 `scene_id`）修到没有错误 → 调用 `render_preview_html`（传 `scene_id`）拿到缩略图拼图，**看图**，检查构图、重叠、出画、节奏是否对上 beat → 修。一个镜头满意了再做下一个。
4. 全部镜头做完后，调用一次不带参数的 `validate_scenes_html` 做全量校验。**不要反复做全量校验或全量预览**——一次完整的全量检查就够了，反复跑只会浪费时间。
5. 最后用一小段话说明：做了什么，每个镜头的每个 beat 对应画面里的什么动作。

## 工具

- `validate_scenes_html(scene_id?)`：静态检查、冒烟运行、确定性、beat 敏感度、字号、字符覆盖、资产。不传 `scene_id` 校验全部镜头。
- `render_preview_html(scene_id)`：对单个镜头抽取关键时刻（镜头首尾、每个 beat 的起点和终点附近，并补均匀采样），返回一张缩略图拼图和每帧指标。
- `suggest_upstream_change`：发现叙事本身有问题（例如某个镜头的 beat 划分让画面无法表达）时，向叙事阶段提出回退建议，不要自己绕过。
