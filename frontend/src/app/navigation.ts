import {
  Boxes,
  Braces,
  Database,
  GitFork,
  Home,
  Inbox,
  Layers,
  Rocket,
  ShieldCheck,
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
  placement?: "footer";
};
export const navigationItems: NavigationItem[] = [
  {
    path: "/admin/overview",
    label: "플랫폼 현황",
    description: "연결 상태·검토할 작업·모델 운영",
    icon: Home,
    group: "",
  },
  {
    path: "/admin/data-catalog",
    label: "데이터 자산",
    description: "데이터 탐색과 자산별 AI 진단",
    icon: Database,
    group: "데이터·의미",
  },
  {
    path: "/admin/semantic-model/ontology",
    label: "온톨로지",
    description: "업무 개념·관계·버전 관리",
    icon: Boxes,
    group: "데이터·의미",
  },
  {
    path: "/admin/semantic-model/bindings",
    label: "의미 연결",
    description: "업무 개념과 자산·용어 연결",
    icon: GitFork,
    group: "데이터·의미",
  },
  {
    path: "/admin/governance",
    label: "메타데이터 공백",
    description: "설명·소유자·분류 누락 확인",
    icon: ShieldCheck,
    group: "거버넌스",
  },
  {
    path: "/admin/changes/review",
    label: "제안 검토",
    description: "AI 변경 제안의 검토·승인·적용",
    icon: Inbox,
    group: "거버넌스",
  },
  {
    path: "/admin/models",
    label: "모델 레지스트리",
    description: "등록 버전·평가 지표·학습 데이터",
    icon: Layers,
    group: "모델 운영",
    modelOperations: true,
  },
  {
    path: "/admin/serving",
    label: "추론 서비스",
    description: "배포 버전·엔드포인트·추론 테스트",
    icon: Rocket,
    group: "모델 운영",
    modelOperations: true,
  },
  {
    path: "/admin/workflows",
    label: "파이프라인",
    description: "운영 파이프라인·스케줄·실행 이력",
    icon: Workflow,
    group: "워크플로",
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
    label: "기능 계약",
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
