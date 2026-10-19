import remarkGfm from 'remark-gfm'
import type { Options } from 'react-markdown'

// 물결표 하나는 취소선으로 보지 않는다 — 답변에 '34.15~34.28%', '09-30~10-12' 같은 범위가 자주 나온다 (취소선은 '~~'만)
export const MARKDOWN_PLUGINS: Options['remarkPlugins'] = [[remarkGfm, { singleTilde: false }]]

// 답변 속 링크(공시 원문 등)는 채팅 화면을 떠나지 않게 새 탭으로 연다
export const MARKDOWN_COMPONENTS: Options['components'] = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
}
