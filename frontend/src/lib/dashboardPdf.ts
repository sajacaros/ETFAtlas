import jsPDF from 'jspdf'
import 'jspdf-autotable'
import type { DashboardSummary, TotalHoldingsResponse, RiskAnalysisResponse } from '@/types/api'
import {
  loadKoreanFont,
  formatNumber,
  formatRate,
  addHeader,
  addSectionTitle,
  addKeyValue,
  downloadPdf,
  getValueColor,
  FONT_NAME,
  PAGE_MARGIN,
  COLORS,
} from './pdfExport'

interface DashboardPdfParams {
  title: string
  summary: DashboardSummary
  riskData?: RiskAnalysisResponse | null
  totalHoldings?: TotalHoldingsResponse | null
  isTotal: boolean
}

export async function generateDashboardPdf(params: DashboardPdfParams): Promise<void> {
  const { title, summary, riskData, totalHoldings, isTotal } = params
  const doc = new jsPDF('p', 'mm', 'a4')
  await loadKoreanFont(doc)

  const today = new Date().toISOString().slice(0, 10)
  let y = addHeader(doc, title, today)

  // 평가금액
  y = addSectionTitle(doc, '평가금액', y)
  y = addKeyValue(doc, '현재 평가금액', `${formatNumber(summary.current_value)}원`, y)
  if (summary.daily) {
    const dailyColor = getValueColor(summary.daily.rate)
    const sign = summary.daily.amount >= 0 ? '+' : ''
    y = addKeyValue(doc, '전일 대비', `${sign}${formatNumber(summary.daily.amount)}원 (${formatRate(summary.daily.rate)})`, y, dailyColor)
  }
  y += 4

  // 투자 정보 (개별 포트폴리오만)
  if (!isTotal) {
    y = addSectionTitle(doc, '투자 정보', y)
    if (summary.invested_amount != null) {
      y = addKeyValue(doc, '투자금액', `${formatNumber(summary.invested_amount)}원`, y)
    }
    if (summary.investment_return) {
      const retColor = getValueColor(summary.investment_return.rate)
      const retSign = summary.investment_return.amount >= 0 ? '+' : ''
      y = addKeyValue(doc, '투자 수익률', `${retSign}${formatNumber(summary.investment_return.amount)}원 (${formatRate(summary.investment_return.rate)})`, y, retColor)
    }
    y += 4
  }

  // 수익률 요약 테이블
  y = addSectionTitle(doc, '수익률 요약', y)
  const summaryItems = [
    { label: '전일대비', item: summary.daily },
    { label: '전달대비', item: summary.monthly },
    { label: '전년대비', item: summary.yearly },
    { label: 'YTD', item: summary.ytd },
  ]

  doc.autoTable({
    startY: y,
    margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
    head: [summaryItems.map(s => s.label)],
    body: [
      summaryItems.map(s => s.item ? `${formatRate(s.item.rate)}\n${s.item.amount >= 0 ? '+' : ''}${formatNumber(s.item.amount)}원` : '-'),
    ],
    styles: { font: FONT_NAME, fontSize: 9, halign: 'center', cellPadding: 4 },
    headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
    theme: 'grid',
  })
  y = doc.lastAutoTable.finalY + 8

  // 리스크 분석 (개별 포트폴리오만)
  if (!isTotal && riskData) {
    y = addSectionTitle(doc, '포트폴리오 리스크', y)
    doc.autoTable({
      startY: y,
      margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
      head: [['MDD', '변동성', '샤프비율']],
      body: [[
        `${riskData.mdd.toFixed(2)}%`,
        `${riskData.volatility.toFixed(2)}%`,
        riskData.sharpe_ratio?.toFixed(2) ?? '-',
      ]],
      styles: { font: FONT_NAME, fontSize: 10, halign: 'center', cellPadding: 4 },
      headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
      theme: 'grid',
    })
    y = doc.lastAutoTable.finalY + 8
  }

  // 종목 비중 테이블 (통합 대시보드만)
  if (isTotal && totalHoldings && totalHoldings.holdings.length > 0) {
    y = addSectionTitle(doc, '종목 비중', y)
    doc.autoTable({
      startY: y,
      margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
      head: [['종목', '수량', '현재가', '평가금액', '비중']],
      body: totalHoldings.holdings.map(h => [
        `${h.name}\n${h.ticker}`,
        formatNumber(h.quantity),
        `${formatNumber(h.current_price)}원`,
        `${formatNumber(h.value)}원`,
        `${h.weight.toFixed(1)}%`,
      ]),
      styles: { font: FONT_NAME, fontSize: 9, cellPadding: 3 },
      headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
      columnStyles: {
        0: { halign: 'left' },
        1: { halign: 'right' },
        2: { halign: 'right' },
        3: { halign: 'right' },
        4: { halign: 'right' },
      },
      theme: 'grid',
    })
  }

  const filename = isTotal
    ? `통합_대시보드_${today}.pdf`
    : `${title}_대시보드_${today}.pdf`
  downloadPdf(doc, filename)
}
