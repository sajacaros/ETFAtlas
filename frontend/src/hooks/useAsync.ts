import { useCallback, useEffect, useRef, useState, type DependencyList } from 'react'

interface AsyncState<T> {
  data: T | undefined
  loading: boolean
  error: unknown
}

/**
 * deps가 바뀔 때마다 fn을 다시 부르고, 이전 요청의 응답은 버린다 (빠르게 다른 항목으로 옮겨 가도 늦게 온 응답이 덮어쓰지 않게).
 * deps가 바뀌면 data를 비우고, reload는 새 응답이 올 때까지 data를 남긴다.
 * fn이 null을 돌려주면(예: id가 아직 없을 때) 요청하지 않고 data를 비운다. reload는 같은 deps로 다시 부른다.
 * deps는 eslint react-hooks/exhaustive-deps가 useEffect처럼 검사한다 (.eslintrc.cjs의 additionalHooks)
 */
export function useAsync<T>(fn: () => Promise<T> | null, deps: DependencyList) {
  const [state, setState] = useState<AsyncState<T>>({ data: undefined, loading: true, error: null })
  const [reloadKey, setReloadKey] = useState(0)
  const lastReloadKey = useRef(reloadKey)

  useEffect(() => {
    // deps가 바뀌었으면 이전 대상의 data를 비우고, reload면 새 응답이 올 때까지 그대로 둔다
    const isReload = lastReloadKey.current !== reloadKey
    lastReloadKey.current = reloadKey
    const promise = fn()
    if (!promise) {
      setState({ data: undefined, loading: false, error: null })
      return
    }
    let ignore = false
    setState((prev) => ({ data: isReload ? prev.data : undefined, loading: true, error: null }))
    promise.then(
      (data) => { if (!ignore) setState({ data, loading: false, error: null }) },
      (error) => { if (!ignore) setState((prev) => ({ ...prev, loading: false, error })) },
    )
    return () => { ignore = true }
    // fn은 매 렌더 새로 만들어지므로 호출한 쪽의 deps(lint가 검사)로만 다시 부른다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadKey])

  const setData = useCallback((data: T | undefined | ((prev: T | undefined) => T | undefined)) => {
    setState((prev) => ({
      ...prev,
      data: typeof data === 'function' ? (data as (p: T | undefined) => T | undefined)(prev.data) : data,
    }))
  }, [])
  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  return { ...state, setData, reload }
}

/**
 * 이벤트 핸들러에서 시작한 요청이 더 새 요청에 밀렸는지 확인한다.
 * const isLatest = beginRequest(); const data = await api(); if (!isLatest()) return
 */
export function useLatestRequest() {
  const seq = useRef(0)
  return useCallback(() => {
    const id = ++seq.current
    return () => id === seq.current
  }, [])
}
