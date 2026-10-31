import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import {
  Background,
  Controls,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  reconnectEdge,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type IsValidConnection,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { FilePlus, FolderOpen, LineChart, Loader2, Play, Plus, Save, Square, Trash2 } from 'lucide-react'
import { flowApi, portfolioApi } from '@/lib/api'
import type { FlowCatalog, FlowGraphData, FlowNodeResult, FlowNodeSpec, FlowTemplate, Portfolio, SavedFlow } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/hooks/use-toast'
import { FlowNodeCard, type FlowCanvasNode, type RunState } from '@/components/flow/FlowNodeCard'
import { NodePalette, DRAG_TYPE } from '@/components/flow/NodePalette'
import { ParamForm } from '@/components/flow/ParamForm'
import { NodeResultView } from '@/components/flow/NodeResultView'
import { FlowPerformance } from '@/components/flow/FlowPerformance'

const NODE_TYPES = { stock: FlowNodeCard }
const DEFAULT_NAME = '새 스크리너'

type RunStatus = { state: RunState; message?: string }

const newId = (type: string) => `${type}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`

function toGraph(nodes: FlowCanvasNode[], edges: Edge[]): FlowGraphData {
  return {
    nodes: nodes.map((n) => ({ id: n.id, type: n.data.spec.type, params: n.data.params, position: n.position })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  }
}

function fromGraph(graph: FlowGraphData, catalog: FlowCatalog): { nodes: FlowCanvasNode[]; edges: Edge[] } {
  const specs = new Map(catalog.nodes.map((s) => [s.type, s]))
  const nodes: FlowCanvasNode[] = graph.nodes
    .filter((n) => specs.has(n.type))
    .map((n, i) => ({
      id: n.id,
      type: 'stock',
      position: n.position ?? { x: i * 260, y: 100 },
      data: { spec: specs.get(n.type)!, params: { ...n.params } },
    }))
  const ids = new Set(nodes.map((n) => n.id))
  const edges = graph.edges
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => ({ id: e.id ?? `${e.source}-${e.target}`, source: e.source, target: e.target }))
  return { nodes, edges }
}

/** target에서 출발해 source에 닿으면 이 연결은 순환을 만든다 */
function createsCycle(edges: Edge[], source: string, target: string) {
  const stack = [target]
  const seen = new Set<string>()
  while (stack.length) {
    const id = stack.pop()!
    if (id === source) return true
    if (seen.has(id)) continue
    seen.add(id)
    edges.filter((e) => e.source === id).forEach((e) => stack.push(e.target))
  }
  return false
}

function FlowEditor() {
  const { toast } = useToast()
  const { screenToFlowPosition, fitView } = useReactFlow()
  const canvasRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const [catalog, setCatalog] = useState<FlowCatalog | null>(null)
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [saved, setSaved] = useState<SavedFlow[]>([])
  const [flowId, setFlowId] = useState<number | null>(null)
  const [name, setName] = useState(DEFAULT_NAME)
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowCanvasNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState('settings')
  const [status, setStatus] = useState<Record<string, RunStatus>>({})
  const [results, setResults] = useState<Record<string, FlowNodeResult>>({})
  const [running, setRunning] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [schedule, setSchedule] = useState({ enabled: false, notify: false })
  const [trackOpen, setTrackOpen] = useState(false)
  // 불러온 노드의 크기를 잰 뒤에 화면에 맞춘다 (재기 전에 맞추면 아주 작게 줌아웃된다)
  const [fitPending, setFitPending] = useState(false)
  const nodesInitialized = useNodesInitialized()

  useEffect(() => {
    if (fitPending && nodesInitialized) {
      fitView({ padding: 0.2, maxZoom: 1 })
      setFitPending(false)
    }
  }, [fitPending, nodesInitialized, fitView])

  useEffect(() => {
    flowApi.getCatalog().then(setCatalog).catch(() => toast({ title: '노드 목록을 불러오지 못했습니다', variant: 'destructive' }))
    portfolioApi.getAll().then(setPortfolios).catch(() => setPortfolios([]))
    flowApi.list().then(setSaved).catch(() => setSaved([]))
  }, [toast])

  useEffect(() => () => abortRef.current?.abort(), [])

  // 저장하지 않은 스크리너에는 자동 실행 설정이 없다
  useEffect(() => {
    if (flowId === null) setSchedule({ enabled: false, notify: false })
  }, [flowId])

  const clearRun = () => {
    setStatus({})
    setResults({})
  }

  const loadGraph = useCallback((graph: FlowGraphData) => {
    if (!catalog) return
    const next = fromGraph(graph, catalog)
    setNodes(next.nodes)
    setEdges(next.edges)
    setSelectedId(null)
    clearRun()
    setFitPending(true)
  }, [catalog, setNodes, setEdges])

  // 캔버스가 비어 있으면 첫 추천 조합으로 시작한다
  useEffect(() => {
    if (catalog && catalog.templates.length && nodes.length === 0 && flowId === null) {
      loadGraph(catalog.templates[0].graph)
      setName(catalog.templates[0].name)
    }
    // 노드 목록을 받은 직후 한 번만 — 사용자가 노드를 모두 지웠을 때 다시 채우지 않는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog])

  const addNode = useCallback((spec: FlowNodeSpec, position?: { x: number; y: number }) => {
    let at = position
    if (!at) {
      const rect = canvasRef.current?.getBoundingClientRect()
      const center = rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : { x: 400, y: 300 }
      at = screenToFlowPosition(center)
      at = { x: at.x - 96 + (nodes.length % 5) * 16, y: at.y - 30 + (nodes.length % 5) * 16 }  // 겹치지 않게 조금씩 비킨다
    }
    const id = newId(spec.type)
    setNodes((ns) => [
      ...ns.map((n) => ({ ...n, selected: false })),
      { id, type: 'stock', position: at!, selected: true, data: { spec, params: {} } },
    ])
    setSelectedId(id)
    setTab('settings')
    setPaletteOpen(false)
  }, [nodes.length, screenToFlowPosition, setNodes])

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    const spec = catalog?.nodes.find((n) => n.type === e.dataTransfer.getData(DRAG_TYPE))
    if (spec) addNode(spec, screenToFlowPosition({ x: e.clientX - 96, y: e.clientY - 30 }))
  }

  // 끝을 끌어 옮기는 중인 연결: 검사할 때 이 연결은 없는 것으로 친다
  const reconnectingRef = useRef<{ id: string; done: boolean } | null>(null)

  const isValidConnection: IsValidConnection = useCallback((c) => {
    if (!c.source || !c.target || c.source === c.target) return false
    const target = nodes.find((n) => n.id === c.target)
    const max = target?.data.spec.max_inputs
    if (max === 0) return false
    const others = edges.filter((e) => e.id !== reconnectingRef.current?.id)
    const incoming = others.filter((e) => e.target === c.target)
    if (incoming.some((e) => e.source === c.source)) return false
    if (max != null && incoming.length >= max) return false
    return !createsCycle(others, c.source, c.target)
  }, [nodes, edges])

  const onConnect = useCallback((c: Connection) => setEdges((es) => addEdge(c, es)), [setEdges])

  const onReconnectStart = useCallback((_: unknown, edge: Edge) => {
    reconnectingRef.current = { id: edge.id, done: false }
  }, [])

  const onReconnect = useCallback((old: Edge, c: Connection) => {
    if (reconnectingRef.current) reconnectingRef.current.done = true
    setEdges((es) => reconnectEdge(old, c, es))
  }, [setEdges])

  // 빈 곳에 놓으면 그 연결을 지운다
  const onReconnectEnd = useCallback((_: unknown, edge: Edge) => {
    if (!reconnectingRef.current?.done) setEdges((es) => es.filter((e) => e.id !== edge.id))
    reconnectingRef.current = null
  }, [setEdges])

  const selected = nodes.find((n) => n.id === selectedId) ?? null

  const updateParam = (key: string, value: unknown) => {
    if (!selected) return
    setNodes((ns) => ns.map((n) => (n.id === selected.id ? { ...n, data: { ...n.data, params: { ...n.data.params, [key]: value } } } : n)))
  }

  const deleteSelected = () => {
    if (!selected) return
    setNodes((ns) => ns.filter((n) => n.id !== selected.id))
    setEdges((es) => es.filter((e) => e.source !== selected.id && e.target !== selected.id))
    setSelectedId(null)
  }

  // 정렬 기준으로 고를 열: 이 노드로 들어오는 노드들의 결과 열
  const fieldOptions = useMemo(() => {
    if (!selected) return []
    const seen = new Map<string, string>()
    edges.filter((e) => e.target === selected.id).forEach((e) => {
      results[e.source]?.dataset.fields.forEach((f) => {
        if (!['code', 'name', 'ai', 'as_of'].includes(f.key) && f.format !== 'text') seen.set(f.key, f.label)
      })
    })
    return [...seen].map(([key, label]) => ({ key, label }))
  }, [selected, edges, results])

  const run = () => {
    if (running) {
      abortRef.current?.abort()
      return
    }
    if (!nodes.length) return
    clearRun()
    setRunning(true)
    let lastDone: string | null = null
    abortRef.current = flowApi.run(toGraph(nodes, edges), {
      onNodeStart: (id) => setStatus((s) => ({ ...s, [id]: { state: 'running' } })),
      onNodeProgress: (id, message) => setStatus((s) => ({ ...s, [id]: { state: 'running', message } })),
      onNodeDone: (r) => {
        lastDone = r.id
        setResults((rs) => ({ ...rs, [r.id]: r }))
        setStatus((s) => ({ ...s, [r.id]: { state: 'done' } }))
      },
      onNodeError: (id, message, skipped) => setStatus((s) => ({ ...s, [id]: { state: skipped ? 'skipped' : 'error', message } })),
      onError: (message) => toast({ title: '실행 실패', description: message, variant: 'destructive' }),
      onRecorded: () => toast({ title: '오늘 고른 종목을 기록했습니다', description: '성과에서 나중에 채점 결과를 볼 수 있습니다' }),
      onDone: () => {
        setRunning(false)
        // 실행 중에 멈춘 노드는 중지로 표시한다
        setStatus((s) => Object.fromEntries(Object.entries(s).map(([k, v]) => [k, v.state === 'running' ? { state: 'skipped', message: '중지됨' } : v])))
        // 고른 노드가 없으면 마지막으로 끝난 노드의 결과를 연다
        setSelectedId((cur) => cur ?? lastDone)
        if (lastDone) {
          setTab('result')
          // 결과 패널이 열려 캔버스가 좁아진 뒤에 다시 맞춘다
          setTimeout(() => fitView({ padding: 0.2, maxZoom: 1, duration: 200 }), 80)
        }
      },
    }, flowId)
  }

  const save = async () => {
    const graph = toGraph(nodes, edges)
    const title = name.trim() || DEFAULT_NAME
    try {
      const flow = flowId ? await flowApi.update(flowId, title, graph) : await flowApi.create(title, graph)
      setFlowId(flow.id)
      setName(flow.name)
      setSchedule({ enabled: flow.schedule_enabled, notify: flow.notify })
      setSaved(await flowApi.list())
      toast({ title: '저장했습니다' })
    } catch {
      toast({ title: '저장 실패', variant: 'destructive' })
    }
  }

  const openSaved = async (id: number) => {
    try {
      const flow = await flowApi.get(id)
      setFlowId(flow.id)
      setName(flow.name)
      setSchedule({ enabled: flow.schedule_enabled, notify: flow.notify })
      if (flow.graph) loadGraph(flow.graph)
    } catch {
      toast({ title: '불러오기 실패', variant: 'destructive' })
    }
  }

  const removeSaved = async (id: number) => {
    if (!window.confirm('이 스크리너를 삭제할까요?')) return
    await flowApi.remove(id)
    setSaved((s) => s.filter((f) => f.id !== id))
    if (flowId === id) setFlowId(null)
  }

  const changeSchedule = async (enabled: boolean, notify: boolean) => {
    if (!flowId) return
    try {
      const flow = await flowApi.setSchedule(flowId, enabled, notify)
      setSchedule({ enabled: flow.schedule_enabled, notify: flow.notify })
    } catch {
      toast({ title: '자동 실행 설정을 바꾸지 못했습니다', variant: 'destructive' })
    }
  }

  const startNew = () => {
    setFlowId(null)
    setName(DEFAULT_NAME)
    setNodes([])
    setEdges([])
    setSelectedId(null)
    clearRun()
  }

  const loadTemplate = (t: FlowTemplate) => {
    setFlowId(null)
    setName(t.name)
    loadGraph(t.graph)
    setPaletteOpen(false)
  }

  // 화면에 그릴 때만 실행 상태를 붙인다 (저장 그래프에는 들어가지 않는다)
  const shownNodes = useMemo(
    () => nodes.map((n) => {
      const s = status[n.id]
      return s ? { ...n, data: { ...n.data, state: s.state, message: s.message, badge: results[n.id]?.badge } } : n
    }),
    [nodes, status, results],
  )

  if (!catalog) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">불러오는 중...</div>
  }

  const palette = <NodePalette catalog={catalog} onAddNode={(s) => addNode(s)} onLoadTemplate={loadTemplate} />
  const selectedStatus = selected ? status[selected.id] : undefined
  const selectedResult = selected ? results[selected.id] : undefined

  return (
    <div className="flex flex-col gap-3 lg:h-[calc(100dvh-4rem)]">
      {/* 도구 막대 */}
      <div className="flex flex-wrap items-center gap-2">
        <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} className="h-9 w-full sm:w-64" aria-label="스크리너 이름" />
        <Button variant="outline" size="sm" onClick={() => setPaletteOpen(true)} className="lg:hidden">
          <Plus className="mr-1 h-4 w-4" /> 노드 추가
        </Button>
        <Button variant="outline" size="sm" onClick={startNew}>
          <FilePlus className="mr-1 h-4 w-4" /> 새로
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              <FolderOpen className="mr-1 h-4 w-4" /> 불러오기
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuLabel>저장한 스크리너</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {saved.length === 0 && <div className="px-2 py-1.5 text-sm text-muted-foreground">저장한 스크리너가 없습니다</div>}
            {saved.map((f) => (
              <DropdownMenuItem key={f.id} onSelect={() => openSaved(f.id)} className="flex items-center justify-between gap-2">
                <span className="truncate">{f.name}</span>
                <button
                  type="button"
                  aria-label={`${f.name} 삭제`}
                  className="rounded p-1 text-muted-foreground hover:text-destructive"
                  onClick={(e) => {
                    e.stopPropagation()
                    e.preventDefault()
                    removeSaved(f.id)
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="outline" size="sm" onClick={save} disabled={!nodes.length}>
          <Save className="mr-1 h-4 w-4" /> 저장
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setTrackOpen(true)}
          disabled={!flowId}
          title={flowId ? undefined : '저장한 스크리너만 기록·자동 실행할 수 있습니다'}
        >
          <LineChart className="mr-1 h-4 w-4" /> 성과
          {schedule.enabled && <span className="ml-1.5 rounded bg-primary/15 px-1 text-[10px] text-primary">자동</span>}
        </Button>
        <Button size="sm" onClick={run} disabled={!nodes.length && !running} className="ml-auto">
          {running ? <><Square className="mr-1 h-4 w-4" /> 중지</> : <><Play className="mr-1 h-4 w-4" /> 실행</>}
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        {/* 팔레트 (데스크톱) */}
        <aside className="hidden w-52 shrink-0 overflow-y-auto pr-1 lg:block">{palette}</aside>

        {/* 캔버스 */}
        <div
          ref={canvasRef}
          className="h-[60vh] min-h-[360px] overflow-hidden rounded-lg border lg:h-auto lg:min-h-0 lg:flex-1"
          onDragOver={(e) => {
            e.preventDefault()
            e.dataTransfer.dropEffect = 'move'
          }}
          onDrop={onDrop}
        >
          <ReactFlow
            nodes={shownNodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onReconnectStart={onReconnectStart}
            onReconnect={onReconnect}
            onReconnectEnd={onReconnectEnd}
            isValidConnection={isValidConnection}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            onNodesDelete={(deleted) => deleted.some((n) => n.id === selectedId) && setSelectedId(null)}
            deleteKeyCode={['Backspace', 'Delete']}
            defaultEdgeOptions={{ style: { strokeWidth: 1.5 } }}
            proOptions={{ hideAttribution: true }}
            minZoom={0.2}
          >
            <Background gap={20} size={1.5} />
            <Controls showInteractive={false} />
            {!selected && (
              <Panel position="top-left" className="max-w-xs rounded-md border bg-background/90 px-3 py-2 text-xs text-muted-foreground shadow-sm">
                노드를 눌러 설정하거나 결과를 봅니다. 노드 오른쪽 점을 다음 노드 왼쪽 점에 끌어 이으면 순서대로 실행되고, 연결 끝을 끌어 다른 노드로 옮기거나 빈 곳에 놓아 지울 수 있고, 고른 노드나 연결은 Delete 키로 지웁니다.
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* 설정·결과 */}
        {selected && (
          <aside className="flex w-full shrink-0 flex-col overflow-hidden rounded-lg border lg:w-[24rem]">
            <div className="border-b p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold">{selected.data.spec.icon} {selected.data.spec.label}</div>
                <Button variant="ghost" size="sm" onClick={deleteSelected} aria-label="노드 삭제">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{selected.data.spec.description}</p>
            </div>
            <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
              <TabsList className="mx-3 mt-3 self-start">
                <TabsTrigger value="settings">설정</TabsTrigger>
                <TabsTrigger value="result">결과</TabsTrigger>
              </TabsList>
              <TabsContent value="settings" className="min-h-0 flex-1 overflow-y-auto p-3">
                {selected.data.spec.params.length ? (
                  <ParamForm
                    specs={selected.data.spec.params}
                    values={selected.data.params}
                    onChange={updateParam}
                    portfolios={portfolios}
                    fieldOptions={fieldOptions}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">설정할 항목이 없습니다.</p>
                )}
              </TabsContent>
              <TabsContent value="result" className="min-h-0 flex-1 overflow-y-auto p-3">
                {selectedResult ? (
                  <NodeResultView result={selectedResult} />
                ) : selectedStatus?.state === 'running' ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> {selectedStatus.message || '실행 중'}
                  </p>
                ) : selectedStatus?.message ? (
                  <p className="text-sm text-destructive">{selectedStatus.message}</p>
                ) : (
                  <p className="text-sm text-muted-foreground">실행하면 이 노드의 결과가 여기에 나옵니다.</p>
                )}
              </TabsContent>
            </Tabs>
          </aside>
        )}
      </div>

      {/* 성과·자동 실행 */}
      <Dialog open={trackOpen} onOpenChange={setTrackOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{name} — 성과·자동 실행</DialogTitle>
          </DialogHeader>
          {flowId && (
            <div className="space-y-5">
              <section className="space-y-2 rounded-lg border p-3">
                <div className="flex items-center gap-3">
                  <Switch id="flow-schedule" checked={schedule.enabled} onCheckedChange={(v) => changeSchedule(v, schedule.notify)} />
                  <Label htmlFor="flow-schedule">영업일 장 마감 뒤 자동 실행</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch
                    id="flow-notify"
                    checked={schedule.notify}
                    disabled={!schedule.enabled}
                    onCheckedChange={(v) => changeSchedule(schedule.enabled, v)}
                  />
                  <Label htmlFor="flow-notify">새로 들어오거나 빠진 종목을 디스코드로 알리기</Label>
                </div>
                <p className="text-xs text-muted-foreground">
                  평일 16:10 이후 그날 일봉이 들어오면 저장된 스크리너를 한 번 돌려 결과를 기록합니다 (휴장일은 건너뜁니다).
                  알림은 관리자가 설정한 디스코드 채널로 가며 스크리너 이름·내 이름·종목 이름이 보입니다.
                  화면에서 직접 실행해도 저장본을 고치지 않았다면 그날 결과로 기록됩니다.
                </p>
              </section>
              <FlowPerformance flowId={flowId} />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 팔레트 (모바일) */}
      <Dialog open={paletteOpen} onOpenChange={setPaletteOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>노드 추가</DialogTitle>
          </DialogHeader>
          {palette}
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default function FlowPage() {
  return (
    <ReactFlowProvider>
      <FlowEditor />
    </ReactFlowProvider>
  )
}
