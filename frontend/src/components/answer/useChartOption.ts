import { useMemo } from 'react'
import type { DataContent } from '@/types/api'
import { useTheme } from '@/hooks/useTheme'
import { buildChartOption, CHART_HEIGHT, DEFAULT_CHART_HEIGHT, PANEL_CHART_HEIGHT, type BuildOptions, type ChartTheme } from './charts'

// 계열 색: 기본 테마는 구분이 잘 되는 색.
// 게임보이 테마는 검은 바탕에서 눈이 부시지 않게 어두운 초록·청록·올리브를 번갈아 쓴다
// (바탕 대비 1.7~3:1, 테마 초록 글씨 대비 4.5:1 이상)
const PALETTE = ['#4f46e5', '#f59e0b', '#10b981', '#ef4444', '#06b6d4', '#8b5cf6', '#ec4899', '#84cc16']
const GAMEBOY_PALETTE = ['#27683d', '#3a5328', '#224f43', '#366339', '#384224', '#1e3e2e', '#315d28', '#2b5a56']

/** CSS 변수(`221 83% 53%`)를 ECharts가 읽는 색으로 */
function cssColor(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value ? `hsl(${value.split(/\s+/).join(', ')})` : '#888'
}

function chartTheme(theme: string): ChartTheme {
  return {
    palette: theme === 'gameboy' ? GAMEBOY_PALETTE : PALETTE,
    tileText: theme === 'gameboy' ? cssColor('--foreground') : '#fff',
    scale: theme === 'gameboy' ? ['#1f3a2a', '#2f7d48'] : ['#818cf8', '#3730a3'],
    other: theme === 'gameboy' ? '#2a2f2c' : '#6b7280',
    text: cssColor('--foreground'),
    muted: cssColor('--muted-foreground'),
    border: cssColor('--border'),
    up: cssColor('--chart-up'),
    down: cssColor('--chart-down'),
    font: getComputedStyle(document.body).fontFamily,
  }
}

export function chartHeight(display: string, content?: DataContent): number {
  if (content?.view.kind === 'candlestick' && content.view.panels?.length) return PANEL_CHART_HEIGHT
  return CHART_HEIGHT[display] ?? DEFAULT_CHART_HEIGHT
}

/** 그릴 수 없으면 null — 호출하는 쪽이 표로 대신 보여준다 */
export function useChartOption(content: DataContent, opts: BuildOptions = {}) {
  const { theme } = useTheme()
  const { panel } = opts
  return useMemo(() => {
    try {
      return buildChartOption(content, chartTheme(theme), { panel })
    } catch {
      return null
    }
  }, [content, theme, panel])
}

