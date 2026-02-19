import { useState, useEffect, useCallback } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight } from 'lucide-react'

interface StoryDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface Chapter {
  title: string
  content: string
}

function splitChapters(text: string): Chapter[] {
  const chapters: Chapter[] = []
  const parts = text.split(/^={8,}$/m)

  // parts 구조: ["", title, content, title, content, ...]
  // ======== 사이에 제목이 있고 그 다음이 본문
  let i = 0
  while (i < parts.length) {
    const part = parts[i].trim()
    // 제목 줄인지 확인 (짧고 비어있지 않으면 제목)
    if (part && !part.includes('\n') && i + 1 < parts.length) {
      // 다음 파트가 본문 (다음 ======== 전까지)
      // 하지만 parts[i+1]이 또 다른 제목일 수도 있음
      const nextPart = parts[i + 1]?.trim()
      if (nextPart === undefined || nextPart === '') {
        // 제목만 있고 본문이 비어있는 경우(예: 첫 번째 타이틀 블록)
        // 부제목 라인이 바로 다음에 올 수 있음 - 스킵
        i++
        continue
      }
      chapters.push({ title: part, content: nextPart })
      i += 2
    } else {
      i++
    }
  }

  // 첫 번째 챕터에 부제목 라인이 포함되어 있으면 분리
  // "ETF Atlas 발표 스크립트\n- Apache AGE..." 같은 헤더 처리
  if (chapters.length > 0 && chapters[0].title.includes('\n')) {
    const lines = chapters[0].title.split('\n')
    chapters[0].title = lines[0]
  }

  return chapters
}

function parseChapterContent(text: string) {
  const lines = text.split('\n')
  const elements: JSX.Element[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    // Subsection: --- title ---
    if (line.startsWith('---') && line.endsWith('---') && line.length > 6) {
      const title = line.replace(/^-+\s*/, '').replace(/\s*-+$/, '').trim()
      if (title) {
        elements.push(
          <h3
            key={key++}
            className="text-lg font-semibold text-foreground mt-8 mb-3 pl-3 border-l-4 border-primary/50 first:mt-0"
          >
            {title}
          </h3>
        )
      }
      i++
      continue
    }

    // Code block: 2+ spaces indentation
    if (line.match(/^ {2,}\S/)) {
      const codeLines: string[] = []
      while (i < lines.length && (lines[i].match(/^ {2,}/) || lines[i].trim() === '')) {
        if (lines[i].trim() === '' && i + 1 < lines.length && !lines[i + 1].match(/^ {2,}/)) {
          break
        }
        codeLines.push(lines[i])
        i++
      }
      const minIndent = Math.min(
        ...codeLines.filter(l => l.trim()).map(l => l.match(/^( *)/)![1].length)
      )
      const code = codeLines.map(l => l.slice(minIndent)).join('\n').trim()
      elements.push(
        <pre
          key={key++}
          className="bg-slate-50 border rounded-lg p-4 my-3 text-sm font-mono overflow-x-auto text-slate-700"
        >
          <code>{code}</code>
        </pre>
      )
      continue
    }

    // Bullet list item
    if (line.match(/^[-·]\s+/)) {
      const items: string[] = []
      while (i < lines.length && lines[i].match(/^[-·]\s+/)) {
        items.push(lines[i].replace(/^[-·]\s+/, '').trim())
        i++
      }
      elements.push(
        <ul key={key++} className="list-disc list-inside space-y-1.5 my-3 text-slate-700 pl-2">
          {items.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      )
      continue
    }

    // Empty line
    if (line.trim() === '') {
      i++
      continue
    }

    // Regular paragraph
    const paraLines: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('---') &&
      !lines[i].match(/^[-·]\s+/) &&
      !lines[i].match(/^ {2,}\S/)
    ) {
      paraLines.push(lines[i].trim())
      i++
    }
    if (paraLines.length > 0) {
      elements.push(
        <p key={key++} className="text-slate-700 leading-relaxed my-2">
          {paraLines.join(' ')}
        </p>
      )
    }
  }

  return elements
}

export default function StoryDialog({ open, onOpenChange }: StoryDialogProps) {
  const [content, setContent] = useState<string | null>(null)
  const [page, setPage] = useState(0)

  useEffect(() => {
    if (open && !content) {
      fetch('/story.txt')
        .then(res => res.text())
        .then(setContent)
    }
  }, [open, content])

  // 다이얼로그 열릴 때 첫 페이지로 리셋
  useEffect(() => {
    if (open) setPage(0)
  }, [open])

  const chapters = content ? splitChapters(content) : []
  const total = chapters.length
  const chapter = chapters[page]

  const goPrev = useCallback(() => setPage(p => Math.max(0, p - 1)), [])
  const goNext = useCallback(() => setPage(p => Math.min(total - 1, p + 1)), [total])

  // 키보드 화살표 네비게이션
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') goPrev()
      if (e.key === 'ArrowRight') goNext()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, goPrev, goNext])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl h-[85vh] flex flex-col p-0">
        {/* 헤더 */}
        <DialogHeader className="px-6 pt-6 pb-4 border-b shrink-0">
          <DialogTitle className="text-2xl">
            {chapter?.title || 'ETF Atlas Story'}
          </DialogTitle>
          <DialogDescription>
            {page + 1} / {total || '-'}
          </DialogDescription>
        </DialogHeader>

        {/* 본문 스크롤 영역 */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {chapter ? (
            parseChapterContent(chapter.content)
          ) : (
            <p className="text-muted-foreground text-center py-8">로딩 중...</p>
          )}
        </div>

        {/* 하단 네비게이션 */}
        <div className="shrink-0 border-t px-6 py-3 flex items-center justify-between bg-slate-50/80">
          <Button
            variant="outline"
            size="sm"
            onClick={goPrev}
            disabled={page === 0}
            className="gap-1"
          >
            <ChevronLeft className="w-4 h-4" />
            이전
          </Button>

          {/* 페이지 인디케이터 */}
          <div className="flex gap-1.5">
            {chapters.map((_, idx) => (
              <button
                key={idx}
                onClick={() => setPage(idx)}
                className={`w-2 h-2 rounded-full transition-colors ${
                  idx === page ? 'bg-primary' : 'bg-slate-300 hover:bg-slate-400'
                }`}
              />
            ))}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={goNext}
            disabled={page === total - 1}
            className="gap-1"
          >
            다음
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
