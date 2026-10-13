import { createContext, useContext } from 'react'

/** 데스크톱 사이드바의 메뉴 아래 빈 자리. 페이지가 createPortal로 자기 내용(챗봇의 대화 목록 등)을 넣는다.
 * 사이드바가 접혀 있으면 null이라 페이지는 자기 화면 안에 따로 보여 줘야 한다. */
export const SidebarSlotContext = createContext<HTMLElement | null>(null)

export function useSidebarSlot(): HTMLElement | null {
  return useContext(SidebarSlotContext)
}
