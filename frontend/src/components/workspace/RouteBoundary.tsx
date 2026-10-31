import { Component, type ReactNode } from "react";
import { Button } from "../ui/button";

export class RouteBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="page-state" role="alert">
        <strong>화면을 열지 못했습니다</strong>
        <p>
          연결을 확인한 뒤 다시 시도하세요. 배포 직후라면 새로고침으로 최신
          화면을 불러올 수 있습니다.
        </p>
        <Button variant="outline" onClick={() => location.reload()}>
          화면 다시 불러오기
        </Button>
      </div>
    ) : (
      this.props.children
    );
  }
}
