import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router'

import EmptyState from './EmptyState'

/**
 * 그리는 중 던져진 오류를 잡아 흰 화면 대신 안내를 보인다.
 * 「다시 열기」는 자식을 다시 그리고, `resetKey`(주소 등)가 바뀌어도 오류를 비운다.
 * 이벤트 핸들러·비동기 오류는 잡지 못한다(React 경계의 한계).
 */
export default class ErrorBoundary extends Component<{ resetKey?: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack)
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.reset()
  }

  reset = () => this.setState({ failed: false })

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <EmptyState
        mood="sad"
        title="화면을 그리지 못했어요"
        action={
          <div className="flex gap-2">
            <button type="button" onClick={this.reset} className="btn-primary btn-md">
              다시 열기
            </button>
            <Link to="/" className="btn-outline btn-md">
              처음으로
            </Link>
          </div>
        }
      >
        잠시 뒤 다시 열어 보세요
      </EmptyState>
    )
  }
}
