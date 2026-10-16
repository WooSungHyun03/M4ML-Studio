import { Component } from "react";
import type { ReactNode } from "react";
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: string }
> {
  state = { error: "" };
  static getDerivedStateFromError(error: Error) {
    return { error: error.message };
  }
  render() {
    if (this.state.error)
      return (
        <main className="welcome">
          <img
            className="brand-logo"
            src="/m4ml-logo.png"
            alt="Media for Machine Laboratory"
          />
          <h1>M4ML Studio 화면을 복원해야 합니다.</h1>
          <p role="alert">
            화면을 표시하는 중 오류가 발생했습니다. 저장된 프로젝트 파일은
            삭제하지 않았습니다.
          </p>
          <div className="actions">
            <button onClick={() => location.reload()}>다시 열기</button>
            <a className="button" href="/">
              프로젝트 목록으로
            </a>
          </div>
          <details>
            <summary>오류 정보</summary>
            <p>{this.state.error}</p>
          </details>
        </main>
      );
    return this.props.children;
  }
}
