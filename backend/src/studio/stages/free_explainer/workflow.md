## 画面的工作流与工具

- `validate_scenes_html(scene_id?)`：静态检查、冒烟运行、确定性、beat 敏感度、字号、字符覆盖、资产。不传 `scene_id` 校验全部镜头。
- `render_preview_html(scene_id)`：对单个镜头抽取关键时刻（镜头首尾、每个 beat 的起点和终点附近，并补均匀采样），返回一张缩略图拼图和每帧指标。
- 先在 `animation/lib/` 里建全片的基底（配色、缓动、常用形状、文字辅助），再**按镜头顺序逐个做**：写场景 → `validate_scenes_html`（传 `scene_id`）修到没有错误 → `render_preview_html`（传 `scene_id`）**看图**，检查构图、重叠、出画、节奏是否对上 beat → 修。一个镜头满意了再做下一个。
- 全部镜头做完后做**一次**不带参数的全量校验；不要反复做全量校验或全量预览。
- 收尾时用一小段话汇报：做了什么，每个镜头的每个 beat 对应画面里的什么动作，哪些需要用户试看试听。

## 背景乐（仅当 `notes/project.md` 写明带背景乐）

用 NumPy 从波形算起合成铺底的背景乐：写独立的 Python 脚本 `music/compose.py`，用 `render_music` 运行、看图、迭代，不用任何采样或现成音源。`STUDIO_TIMELINE` 指向的时间轴由 `render_music` 按当前叙事与配音即时生成（下文提到的 `upstream/timeline.json` 在本项目里不存在，内容相同）。**先把叙事和配音定下来再做配乐**：配音一变，配乐就要重新渲染。不带背景乐的项目不要写 `music/compose.py`。

