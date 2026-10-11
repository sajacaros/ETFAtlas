import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart, PieChart, RadarChart, TreemapChart } from 'echarts/charts'
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, BarChart, PieChart, TreemapChart, RadarChart, CandlestickChart,
  GridComponent, TooltipComponent, LegendComponent, RadarComponent, CanvasRenderer,
])

/** ECharts 런타임은 이 파일에만 둔다 — 차트를 처음 그릴 때 따로 불러온다 (AnswerView의 lazy import) */
export default function ChartView({ option, height }: { option: echarts.EChartsCoreOption; height: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ height }} className="w-full" />
}
