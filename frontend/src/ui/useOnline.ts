import { onlineManager } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

/** 인터넷이 이어져 있는지. 요청을 멈추고 잇는 TanStack Query와 같은 값을 본다(#1722). */
export const useOnline = () => useSyncExternalStore((notify) => onlineManager.subscribe(notify), () => onlineManager.isOnline())
