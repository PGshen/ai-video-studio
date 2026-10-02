import type { Component } from 'vue'
import {
  BrainIcon,
  FilePenLineIcon,
  FileTextIcon,
  GlobeIcon,
  LinkIcon,
  SearchIcon,
  SquareTerminalIcon,
  WrenchIcon,
} from '@lucide/vue'
import type { ToolKind } from '@/components/session/toolPresentation'

export const THINKING_ICON: Component = BrainIcon

const ICONS: Record<ToolKind, Component> = {
  read: FileTextIcon,
  write: FilePenLineIcon,
  glob: SearchIcon,
  grep: SearchIcon,
  bash: SquareTerminalIcon,
  'web-search': GlobeIcon,
  'web-fetch': LinkIcon,
  generic: WrenchIcon,
}

export function iconFor(kind: ToolKind): Component {
  return ICONS[kind]
}
