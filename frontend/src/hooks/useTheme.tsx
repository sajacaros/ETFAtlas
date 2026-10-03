import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'

export type Theme = 'default' | 'gameboy'

const STORAGE_KEY = 'theme'

interface ThemeContextType {
  theme: Theme
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextType>({
  theme: 'gameboy',
  toggle: () => {},
})

function readTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'default' ? 'default' : 'gameboy'
  } catch {
    return 'gameboy'
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readTheme)

  // 게임보이 테마는 다크 계열이라 dark 클래스도 함께 붙여 dark: 변형(prose-invert 등)을 쓰게 한다
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('theme-gameboy', theme === 'gameboy')
    root.classList.toggle('dark', theme === 'gameboy')
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === 'gameboy' ? 'default' : 'gameboy'
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // 저장소를 못 쓰면 이번 세션에만 적용한다
      }
      return next
    })
  }, [])

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
