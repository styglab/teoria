import {
  Boxes,
  Braces,
  Database,
  FileText,
  Home,
  Inbox,
  Layers,
  Rocket,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export const navigationPaths = {
  overview: "/admin/overview",
  dataCatalog: "/admin/data-catalog",
  ontology: "/admin/semantic-model/ontology",
  goodsDictionary: "/admin/domains/goods/dictionary",
  review: "/admin/changes/review",
  workflows: "/admin/workflows",
  models: "/admin/models",
  images: "/admin/images",
  serving: "/admin/serving",
  formatid: "/admin/specifications",
  operations: "/admin/operations",
  capabilities: "/admin/developer/capabilities",
} as const;

export const navigationGroups = [
  {
    id: "data",
    label: "데이터",
    description: "데이터 자산과 스키마·품질·계보를 관리합니다.",
    icon: Database,
  },
  {
    id: "ontology",
    label: "Ontology",
    description: "업무 개념·관계·의미 연결과 게시 계약 실행을 관리합니다.",
    icon: Boxes,
  },
  {
    id: "mlops",
    label: "MLOps",
    description: "등록 모델의 평가 결과와 배포된 추론 서비스를 관리합니다.",
    icon: Layers,
  },
  {
    id: "goods_domain",
    label: "도메인 관리",
    description: "물품 도메인의 공통 정의와 품목별 적용 범위를 관리합니다.",
    icon: Boxes,
  },
  {
    id: "apps",
    label: "업무 앱",
    description: "업무별 데이터와 결과를 활용합니다.",
    icon: FileText,
  },
  {
    id: "common_operations",
    label: "공통 운영",
    description: "모든 작업의 실행과 연결·접근 설정을 관리합니다.",
    icon: Workflow,
  },
] as const;

export type NavigationItem = {
  path: string;
  label: string;
  description: string;
  icon: LucideIcon;
  group: (typeof navigationGroups)[number]["id"] | "";
  modelOperations?: boolean;
  module?: "semantic" | "formatid" | "mlops";
  placement?: "footer";
  availableIn?: Array<"semantic" | "formatid" | "mlops">;
};
export const navigationItems: NavigationItem[] = [
  {
    path: navigationPaths.overview,
    label: "홈",
    description: "검토 대기·실패한 실행·최근 작업",
    icon: Home,
    group: "",
  },
  {
    path: navigationPaths.dataCatalog,
    module: "semantic",
    label: "데이터 자산",
    description: "데이터 탐색과 자산별 AI 진단",
    icon: Database,
    group: "data",
  },
  {
    path: navigationPaths.ontology,
    module: "semantic",
    label: "온톨로지",
    description: "업무 개념·관계·버전 관리",
    icon: Boxes,
    group: "ontology",
  },
  {
    path: navigationPaths.goodsDictionary,
    availableIn: ["semantic", "formatid"],
    label: "물품 사전",
    description: "품목별 유형·속성·원문 표현과 공통 정의 관리",
    icon: Boxes,
    group: "goods_domain",
  },
  {
    path: navigationPaths.review,
    module: "semantic",
    label: "검토함",
    description: "제안·의미 연결·온톨로지 검토",
    icon: Inbox,
    group: "ontology",
  },
  {
    path: navigationPaths.workflows,
    label: "파이프라인",
    description: "의미 작성·문서 처리·모델 학습·배포의 공통 실행 이력",
    icon: Workflow,
    group: "common_operations",
    placement: "footer",
  },
  {
    path: navigationPaths.models,
    module: "mlops",
    label: "모델 레지스트리",
    description: "등록 버전·평가 지표·학습 데이터",
    icon: Layers,
    group: "mlops",
    modelOperations: true,
  },
  {
    path: navigationPaths.serving,
    module: "mlops",
    label: "추론 서비스",
    description: "배포 버전·엔드포인트·추론 테스트",
    icon: Rocket,
    group: "mlops",
    modelOperations: true,
  },
  {
    path: navigationPaths.formatid,
    module: "formatid",
    label: "FormatID",
    description: "규격서 기반 물품 구조화·분석",
    icon: FileText,
    group: "apps",
  },
  {
    path: navigationPaths.images,
    label: "컨테이너 이미지",
    description: "모델 학습·서빙 이미지와 버전 참조",
    icon: Boxes,
    group: "common_operations",
    placement: "footer",
  },
  {
    path: navigationPaths.operations,
    label: "연결 및 설정",
    description: "외부 연결·실행 도구·접근 정보",
    icon: Wrench,
    group: "common_operations",
    placement: "footer",
  },
  {
    path: navigationPaths.capabilities,
    module: "semantic",
    label: "실행 계약·Capability",
    description: "Source·Mapping·Capability의 연결과 계약 검증",
    icon: Braces,
    group: "ontology",
  },
];
export function currentNavigation(path: string) {
  return (
    navigationItems.find(
      (item) => path === item.path || path.startsWith(item.path + "/"),
    ) ?? navigationItems[0]
  );
}

export function navigationAvailable(
  item: NavigationItem,
  modules: { semantic: boolean; formatid: boolean; mlops: boolean },
) {
  return (
    (!item.module || modules[item.module]) &&
    (!item.availableIn || item.availableIn.some((module) => modules[module]))
  );
}
