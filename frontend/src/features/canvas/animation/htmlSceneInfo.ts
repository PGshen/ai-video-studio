import type { HtmlPreviewSection } from '@/types/api'
import type { NarrativeSceneInfo } from './narrativeScenes'

/** 镜头详情的"Beats"标签用的内容：HTML 画布只有 meta（标签和各 beat 的旁白），没有叙事全文。 */
export function sceneInfoFromSection(section: HtmlPreviewSection): NarrativeSceneInfo {
  return {
    id: section.id,
    narration: '',
    visualIntent: section.label,
    beats: section.beats.map((beat) => ({
      cueText: beat.cue_text,
      visualAction: '',
      emphasis: '',
      transition: '',
    })),
  }
}
