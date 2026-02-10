import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface AmountVisibilityContextType {
  visible: boolean
  toggle: () => void
}

const AmountVisibilityContext = createContext<AmountVisibilityContextType>({
  visible: false,
  toggle: () => {},
})

const STORAGE_KEY = 'etf-atlas-amount-visible'

export function AmountVisibilityProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  const toggle = useCallback(() => {
    setVisible((prev) => {
      const next = !prev
      try {
        localStorage.setItem(STORAGE_KEY, String(next))
      } catch {
        // ignore
      }
      return next
    })
  }, [])

  return (
    <AmountVisibilityContext.Provider value={{ visible, toggle }}>
      {children}
    </AmountVisibilityContext.Provider>
  )
}

export function useAmountVisibility() {
  return useContext(AmountVisibilityContext)
}

const MASK = '••••••'

export function formatMaskedNumber(n: number, visible: boolean): string {
  if (!visible) return MASK
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}
