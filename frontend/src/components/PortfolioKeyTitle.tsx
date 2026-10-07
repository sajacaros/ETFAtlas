import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import { copyText } from '@/lib/clipboard'

/** 포트폴리오 이름. 누르면 챗봇의 `/portfolio <키>` 명령에 쓰는 키를 복사한다 */
export default function PortfolioKeyTitle({ name, chatKey, className }: {
  name: string
  chatKey: string
  className?: string
}) {
  const { toast } = useToast()

  // 복사마저 실패하면 키를 보여 주고 직접 입력하게 한다
  const copy = async () => {
    try {
      await copyText(chatKey)
      toast({ title: '포트폴리오 키를 복사했습니다', description: `챗봇에서 /portfolio ${chatKey} 뒤에 질문을 이어 쓰세요.` })
    } catch {
      toast({ title: '복사하지 못했습니다', description: `키: ${chatKey}`, variant: 'destructive' })
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={`눌러서 포트폴리오 키 복사 (${chatKey})`}
      className={cn('text-left hover:underline underline-offset-4 decoration-dotted cursor-copy', className)}
    >
      {name}
    </button>
  )
}
