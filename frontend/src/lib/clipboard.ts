/**
 * 텍스트를 클립보드에 복사한다. 실패하면 예외를 던진다.
 *
 * http로 접속하면 보안 컨텍스트가 아니라서 navigator.clipboard가 없다.
 * 그때는 숨긴 textarea를 선택해 execCommand('copy')로 복사한다.
 */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.opacity = '0'
  // 다이얼로그는 포커스를 가두므로 그 안에 붙여야 선택이 풀리지 않는다
  const previous = document.activeElement as HTMLElement | null
  const host = previous?.closest('[role="dialog"]') ?? document.body
  host.appendChild(textarea)
  try {
    textarea.select()
    if (!document.execCommand('copy')) throw new Error('copy command failed')
  } finally {
    textarea.remove()
    previous?.focus()
  }
}
