import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface AmountVisibilityContextType {
  visible: boolean
  toggle: () => void
}

const AmountVisibilityContext = createContext<AmountVisibilityContextType>({
  visible: false,
  toggle: () => {},
})

export function AmountVisibilityProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(false)

  const toggle = useCallback(() => {
    setVisible((prev) => !prev)
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
