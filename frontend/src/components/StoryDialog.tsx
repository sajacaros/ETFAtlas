import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@/components/ui/dialog'

interface StoryDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function StoryDialog({ open, onOpenChange }: StoryDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[95vw] h-[90vh] p-0 overflow-hidden">
        <DialogTitle className="sr-only">ETF Atlas Story</DialogTitle>
        {open && (
          <iframe
            src="/story.html"
            className="w-full h-full border-0"
            title="ETF Atlas Story"
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
