import {
  Boxes,
  Braces,
  Database,
  GitFork,
  Home,
  Inbox,
  Layers,
  Rocket,
  FileText,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export type NavigationItem = {
  path: string;
  label: string;
  description: string;
  icon: LucideIcon;
  group: string;
  modelOperations?: boolean;
  module?: "semantic" | "formatid" | "mlops";
  placement?: "footer";
};
export const navigationItems: NavigationItem[] = [
  {
    path: "/admin/overview",
    label: "홈",
    description: "검토 대기·실패한 실행·최근 작업",
    icon: Home,
    group: "",
  },
  {
    path: "/admin/data-catalog",
    module: "semantic",
    label: "데이터 자산",
    description: "데이터 탐색과 자산별 AI 진단",
    icon: Database,
    group: "탐색",
  },
  {
    path: "/admin/semantic-model/ontology",
    module: "semantic",
    label: "온톨로지",
    description: "업무 개념·관계·버전 관리",
    icon: Boxes,
    group: "의미 모델",
  },
  {
    path: "/admin/semantic-model/bindings",
    module: "semantic",
    label: "의미 연결",
    description: "업무 개념과 자산·용어 연결",
    icon: GitFork,
    group: "의미 모델",
  },
  {
    path: "/admin/changes/review",
    module: "semantic",
    label: "검토함",
    description: "제안·의미 연결·온톨로지 검토",
    icon: Inbox,
    group: "검토",
  },
  {
    path: "/admin/workflows",
    label: "파이프라인",
    description: "운영 파이프라인·스케줄·실행 이력",
    icon: Workflow,
    group: "워크플로",
  },
  {
    path: "/admin/models",
    module: "mlops",
    label: "모델 레지스트리",
    description: "등록 버전·평가 지표·학습 데이터",
    icon: Layers,
    group: "모델 운영",
    modelOperations: true,
  },
  {
    path: "/admin/serving",
    module: "mlops",
    label: "추론 서비스",
    description: "배포 버전·엔드포인트·추론 테스트",
    icon: Rocket,
    group: "모델 운영",
    modelOperations: true,
  },
  {
    path: "/admin/specifications",
    module: "formatid",
    label: "FormatID",
    description: "규격서 기반 물품 구조화·분석",
    icon: FileText,
    group: "앱",
  },
  {
    path: "/admin/operations",
    label: "연결 및 설정",
    description: "외부 연결·실행 도구·접근 정보",
    icon: Wrench,
    group: "플랫폼 관리",
    placement: "footer",
  },
  {
    path: "/admin/developer/capabilities",
    module: "semantic",
    label: "개발 도구",
    description: "Capability·Runtime 개발 도구",
    icon: Braces,
    group: "플랫폼 관리",
    placement: "footer",
  },
];
export function currentNavigation(path: string) {
  return (
    navigationItems.find(
      (item) => path === item.path || path.startsWith(item.path + "/"),
    ) ?? navigationItems[0]
  );
}
