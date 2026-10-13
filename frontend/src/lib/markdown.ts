import remarkGfm from 'remark-gfm'
import type { Options } from 'react-markdown'

// 물결표 하나는 취소선으로 보지 않는다 — 답변에 '34.15~34.28%', '09-30~10-12' 같은 범위가 자주 나온다 (취소선은 '~~'만)
export const MARKDOWN_PLUGINS: Options['remarkPlugins'] = [[remarkGfm, { singleTilde: false }]]
