import { useMemo } from 'react'
import type { DataContent } from '@/types/api'
import { useTheme } from '@/hooks/useTheme'
import { buildChartOption, CHART_HEIGHT, DEFAULT_CHART_HEIGHT, type ChartTheme } from './charts'

// 계열 색: 기본 테마는 구분이 잘 되는 색, 게임보이 테마는 초록 계열에서 밝기 차이가 큰 순서로
const PALETTE = ['#4f46e5', '#f59e0b', '#10b981', '#ef4444', '#06b6d4', '#8b5cf6', '#ec4899', '#84cc16']
const GAMEBOY_PALETTE = ['#22ff55', '#f0fdf4', '#15803d', '#a3e635', '#86efac', '#166534', '#4ade80', '#65a30d']

/** CSS 변수(`221 83% 53%`)를 ECharts가 읽는 색으로 */
function cssColor(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value ? `hsl(${value.split(/\s+/).join(', ')})` : '#888'
}

function chartTheme(theme: string): ChartTheme {
  return {
    palette: theme === 'gameboy' ? GAMEBOY_PALETTE : PALETTE,
    text: cssColor('--foreground'),
    muted: cssColor('--muted-foreground'),
    border: cssColor('--border'),
    up: cssColor('--chart-up'),
    down: cssColor('--chart-down'),
    font: getComputedStyle(document.body).fontFamily,
  }
}

export function chartHeight(display: string): number {
  return CHART_HEIGHT[display] ?? DEFAULT_CHART_HEIGHT
}

/** 그릴 수 없으면 null — 호출하는 쪽이 표로 대신 보여준다 */
export function useChartOption(content: DataContent) {
  const { theme } = useTheme()
  return useMemo(() => {
    try {
      return buildChartOption(content, chartTheme(theme))
    } catch {
      return null
    }
  }, [content, theme])
}

