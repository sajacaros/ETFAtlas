import { useEffect, useState, useRef } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { arrayMove } from '@dnd-kit/sortable'
import { portfolioApi } from '@/lib/api'
import { useToast } from '@/hooks/use-toast'
import { useAsync } from '@/hooks/useAsync'
import { usePortfolioDraft } from '@/hooks/usePortfolioDraft'
import type { Portfolio, DashboardSummary } from '@/types/api'
import PortfolioList from './portfolio/PortfolioList'
import PortfolioDetailView from './portfolio/PortfolioDetailView'
import type { NewPortfolioParams } from './portfolio/CreatePortfolioDialog'

// /portfolio는 목록, /portfolio/:id는 상세
export default function PortfolioPage() {
  const { toast } = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const { id: idParam } = useParams<{ id: string }>()
  const selectedId = idParam && /^\d+$/.test(idParam) ? Number(idParam) : null

  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [loading, setLoading] = useState(true)
  const [totalSummary, setTotalSummary] = useState<DashboardSummary | null>(null)
  const [batchSaving, setBatchSaving] = useState(false)

  // 상세와 계산 결과는 선택한 id마다 새로 받는다 — 다른 포트폴리오로 옮겨 가면 늦게 온 이전 응답은 버린다
  // id가 없으면(목록) null을 돌려줘 부르지 않는다
  const detailState = useAsync(() => (selectedId ? portfolioApi.get(selectedId) : null), [selectedId])
  const calcState = useAsync(() => (selectedId ? portfolioApi.calculate(selectedId) : null), [selectedId])
  const detail = detailState.data ?? null
  const calcResult = calcState.data ?? null
  const draft = usePortfolioDraft(detail, calcResult)
  const { sync: syncDraft, end: endEdit } = draft

  // 저장이 끝났을 때 아직 같은 포트폴리오를 보고 있는지 확인한다
  const selectedIdRef = useRef(selectedId)
  selectedIdRef.current = selectedId

  useEffect(() => {
    const fetchPortfolios = async () => {
      try {
        const data = await portfolioApi.getAll()
        setPortfolios(data)
      } catch {
        console.error('Failed to fetch portfolios')
      } finally {
        setLoading(false)
      }
    }
    const fetchTotalSummary = async () => {
      try {
        const { summary } = await portfolioApi.getTotalDashboard()
        setTotalSummary(summary)
      } catch {
        // 스냅샷이 없는 경우 무시
      }
    }
    fetchPortfolios()
    fetchTotalSummary()
  }, [])

  // 다른 포트폴리오로 옮기거나 목록으로 나가면 편집을 버린다
  useEffect(() => {
    endEdit()
  }, [selectedId, endEdit])

  // 상세를 새로 받으면 이름·목표 금액·예수금 입력값을 맞춘다
  useEffect(() => {
    if (detail) syncDraft(detail)
  }, [detail, syncDraft])

  useEffect(() => {
    if (!detailState.error) return
    toast({ title: '포트폴리오 로드 실패', variant: 'destructive' })
    navigate('/portfolio', { replace: true })
  }, [detailState.error, toast, navigate])

  useEffect(() => {
    if (calcState.error) console.error('Failed to calculate')
  }, [calcState.error])

  // 구성종목 분석에서 저장하고 넘어오면(state.selectId) 새 포트폴리오를 바로 연다 — 뒤로 가면 목록이 나오게 목록 위에 쌓는다
  const pendingSelectId = (location.state as { selectId?: number } | null)?.selectId
  const handledLocationKey = useRef<string | null>(null)
  useEffect(() => {
    if (!pendingSelectId || handledLocationKey.current === location.key) return
    handledLocationKey.current = location.key
    navigate('/portfolio', { replace: true, state: null })
    navigate(`/portfolio/${pendingSelectId}`)
  }, [pendingSelectId, location.key, navigate])

  const selectPortfolio = (id: number) => navigate(`/portfolio/${id}`)

  // 목록에서 들어왔으면 뒤로 가기, 주소로 바로 들어왔으면 목록으로
  const goBack = () => {
    if (location.key !== 'default') navigate(-1)
    else navigate('/portfolio')
  }

  const handleReorder = async (activeId: number, overId: number) => {
    const oldIndex = portfolios.findIndex((p) => p.id === activeId)
    const newIndex = portfolios.findIndex((p) => p.id === overId)
    const reordered = arrayMove(portfolios, oldIndex, newIndex)
    setPortfolios(reordered)

    const orders = reordered.map((p, i) => ({ id: p.id, display_order: i }))
    try {
      await portfolioApi.reorder(orders)
    } catch {
      const data = await portfolioApi.getAll()
      setPortfolios(data)
      toast({ title: '순서 변경 실패', variant: 'destructive' })
    }
  }

  const handleCreate = async (params: NewPortfolioParams) => {
    try {
      const p = await portfolioApi.create(params)
      setPortfolios((prev) => [...prev, p])
      toast({ title: '포트폴리오가 생성되었습니다' })
      return true
    } catch {
      toast({ title: '생성 실패', variant: 'destructive' })
      return false
    }
  }

  const handleDuplicate = async (id: number) => {
    try {
      const p = await portfolioApi.duplicate(id)
      setPortfolios((prev) => [...prev, p])
      toast({ title: `'${p.name}'이(가) 생성되었습니다` })
    } catch {
      toast({ title: '복제 실패', variant: 'destructive' })
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await portfolioApi.delete(id)
      setPortfolios((prev) => prev.filter((p) => p.id !== id))
      toast({ title: '포트폴리오가 삭제되었습니다' })
    } catch {
      toast({ title: '삭제 실패', variant: 'destructive' })
    }
  }

  const applySnapshotToggle = async (id: number, enabled: boolean) => {
    try {
      await portfolioApi.update(id, { snapshot_enabled: enabled })
      const data = await portfolioApi.getAll()
      setPortfolios(data)
      toast({ title: enabled ? '스냅샷이 활성화되었습니다' : '스냅샷을 끄고 기록을 삭제했습니다' })
    } catch {
      toast({ title: '스냅샷 설정 변경 실패', variant: 'destructive' })
    }
  }

  const handleRefresh = () => {
    detailState.reload()
    calcState.reload()
  }

  const handleBatchSave = async () => {
    if (!detail) return
    const id = detail.id
    setBatchSaving(true)
    try {
      const updated = await portfolioApi.batchUpdate(id, draft.buildBatchPayload(detail))
      if (selectedIdRef.current === id) {
        detailState.setData(updated)
        calcState.reload()
      }
      const data = await portfolioApi.getAll()
      setPortfolios(data)

      if (selectedIdRef.current === id) endEdit()
      toast({ title: '변경사항이 저장되었습니다' })
    } catch {
      toast({ title: '저장 실패', variant: 'destructive' })
    } finally {
      setBatchSaving(false)
    }
  }

  if (loading || (selectedId && detail?.id !== selectedId && detailState.loading)) {
    return <div className="text-center py-12">로딩 중...</div>
  }

  // Detail view
  if (selectedId && detail && detail.id === selectedId) {
    return (
      <PortfolioDetailView
        detail={detail}
        portfolio={portfolios.find((pf) => pf.id === selectedId)}
        calcResult={calcResult}
        calcLoading={calcState.loading}
        draft={draft}
        saving={batchSaving}
        onBack={goBack}
        onRefresh={handleRefresh}
        onSave={handleBatchSave}
      />
    )
  }

  // List view
  return (
    <PortfolioList
      portfolios={portfolios}
      totalSummary={totalSummary}
      onSelect={selectPortfolio}
      onCreate={handleCreate}
      onDuplicate={handleDuplicate}
      onDelete={handleDelete}
      onSnapshotToggle={applySnapshotToggle}
      onReorder={handleReorder}
    />
  )
}
