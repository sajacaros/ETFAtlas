import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@/components/ui/dialog'

// 사이드바에서 여는 정적 문서 페이지 (public/*.html)
export interface DocPage {
  src: string
  title: string
}

export const DOC_PAGES = {
  story: { src: '/story.html', title: 'ETF Atlas Story' },
  architecture: { src: '/architecture.html', title: 'ETF Atlas Chatbot Architecture' },
} satisfies Record<string, DocPage>

interface DocDialogProps {
  doc: DocPage | null
  onClose: () => void
}

export default function DocDialog({ doc, onClose }: DocDialogProps) {
  return (
    <Dialog open={doc !== null} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-5xl w-[95vw] h-[90vh] p-0 overflow-hidden">
        <DialogTitle className="sr-only">{doc?.title}</DialogTitle>
        {doc && (
          <iframe
            src={doc.src}
            className="w-full h-full border-0"
            title={doc.title}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
