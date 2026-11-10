import { customerChurnTest } from "../examples/customer_churn/PredictionForm";
import { lazy, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { WorkspaceFrame } from "../components/workspace/WorkspaceLayout";
import { AdminAccess } from "../platform/access_control/AdminAccess";
import { navigationPaths } from "./navigation";
import { OperationsSettings, Overview } from "./overview/Overview";
import { WorkspaceChoices } from "./WorkspaceChoices";
const Pipelines = lazy(() =>
  import("../platform/workflow_management/Pipelines").then((module) => ({
    default: module.Pipelines,
  })),
);
const ImageRegistry = lazy(() =>
  import("../platform/mlops/ImageRegistry").then((module) => ({
    default: module.ImageRegistry,
  })),
);
const ModelOperations = lazy(() =>
  import("../platform/mlops/ModelOperations").then((module) => ({
    default: module.ModelOperations,
  })),
);
const GoodsDictionary = lazy(() =>
  import("../domains/goods/expression_links/GoodsDictionary").then(
    (module) => ({ default: module.GoodsDictionary }),
  ),
);
const ApplicationStandards = lazy(() =>
  import("../apps/formatid/ApplicationStandards").then((module) => ({
    default: module.ApplicationStandards,
  })),
);
const CapabilityWorkspace = lazy(() =>
  import("../platform/ontology/runtime/capability/CapabilityStudio").then(
    (module) => ({
      default: module.CapabilityWorkspace,
    }),
  ),
);
const SuggestionReview = lazy(() =>
  import("../platform/data/metadata/intelligence/SuggestionReview").then(
    (module) => ({
      default: module.SuggestionReview,
    }),
  ),
);
const MetadataExplorer = lazy(() =>
  import("../platform/data/metadata/catalog/MetadataExplorer").then(
    (module) => ({
      default: module.MetadataExplorer,
    }),
  ),
);
const MetadataAssetPage = lazy(() =>
  import("../platform/data/metadata/catalog/MetadataAssetPage").then(
    (module) => ({
      default: module.MetadataAssetPage,
    }),
  ),
);
const ReviewInbox = lazy(() =>
  import("../platform/data/metadata/intelligence/ReviewInbox").then(
    (module) => ({
      default: module.ReviewInbox,
    }),
  ),
);
const SpecificationWorkspace = lazy(() =>
  import("../apps/formatid/SpecificationWorkspace").then((module) => ({
    default: module.SpecificationWorkspace,
  })),
);
const OntologyAuthoring = lazy(() =>
  import("../platform/ontology/authoring/OntologyAuthoring").then((module) => ({
    default: module.OntologyAuthoring,
  })),
);

export function WorkspaceRoutes({
  modelOperationsEnabled,
}: {
  modelOperationsEnabled: boolean;
}) {
  return (
    <Routes>
      <Route
        path="/"
        element={<Navigate to={navigationPaths.overview} replace />}
      />
      <Route
        path="/admin"
        element={<Navigate to={navigationPaths.overview} replace />}
      />
      <Route
        path={navigationPaths.overview}
        element={workspacePage(
          <Overview
            workspaceChoices={
              <WorkspaceChoices
                modelOperationsEnabled={modelOperationsEnabled}
              />
            }
          />,
        )}
      />
      <Route
        path="/admin/governance"
        element={workspacePage(
          <Navigate to="/admin/data-catalog?filter=description" replace />,
        )}
      />
      <Route
        path={navigationPaths.formatid}
        element={workspacePage(<SpecificationWorkspace />, true)}
      />
      <Route
        path={navigationPaths.workflows}
        element={workspacePage(<Pipelines />, true)}
      />
      <Route
        path={navigationPaths.images}
        element={workspacePage(<ImageRegistry />, true)}
      />
      <Route
        path={navigationPaths.models}
        element={workspacePage(<ModelOperations view="models" />, true)}
      />
      <Route
        path={navigationPaths.serving}
        element={workspacePage(
          <ModelOperations
            view="serving"
            renderInferenceTest={customerChurnTest}
          />,
          true,
        )}
      />
      <Route path="/admin/model-operations" element={<LegacyModelRoute />} />
      <Route
        path={navigationPaths.operations}
        element={workspacePage(<OperationsSettings />)}
      />
      <Route
        path={navigationPaths.capabilities}
        element={workspacePage(<CapabilityWorkspace />)}
      />
      <Route
        path={navigationPaths.dataCatalog}
        element={workspacePage(<MetadataExplorer />)}
      />
      <Route
        path={`${navigationPaths.dataCatalog}/assets/:fqn`}
        element={workspacePage(<MetadataAssetPage />)}
      />
      <Route
        path={navigationPaths.review}
        element={workspacePage(<ReviewInbox />, true)}
      />
      <Route
        path={navigationPaths.goodsDictionary}
        element={workspacePage(<GoodsDictionary />, true)}
      />
      <Route
        path="/admin/semantic-model/goods-dictionary"
        element={<LegacySemanticRoute kind="dictionary" />}
      />
      <Route
        path={`${navigationPaths.formatid}/standards`}
        element={workspacePage(<ApplicationStandards />, true)}
      />
      <Route
        path="/admin/semantic-model/bindings"
        element={<LegacySemanticRoute kind="bindings" />}
      />
      <Route
        path={navigationPaths.ontology}
        element={workspacePage(<OntologyAuthoring />, true)}
      />
      <Route
        path="/admin/settings"
        element={<Navigate to={navigationPaths.operations} replace />}
      />
      <Route
        path="/admin/ask"
        element={<Navigate to={navigationPaths.capabilities} replace />}
      />
      <Route
        path="/admin/capabilities"
        element={<Navigate to={navigationPaths.capabilities} replace />}
      />
      <Route
        path="/admin/review-queue"
        element={<Navigate to={navigationPaths.review} replace />}
      />
      <Route
        path="/admin/semantic-bindings"
        element={<Navigate to="/admin/semantic-model/bindings" replace />}
      />
      <Route
        path="/admin/business-concepts"
        element={<Navigate to={navigationPaths.ontology} replace />}
      />
      <Route
        path="*"
        element={<Navigate to={navigationPaths.overview} replace />}
      />
    </Routes>
  );
}

function LegacyModelRoute() {
  const location = useLocation();
  return (
    <Navigate
      to={{
        pathname: "/admin/models",
        search: location.search,
        hash: location.hash,
      }}
      replace
    />
  );
}

function LegacySemanticRoute({ kind }: { kind: "bindings" | "dictionary" }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  let path = navigationPaths.goodsDictionary as string;
  if (kind === "bindings") {
    path = navigationPaths.ontology;
    params.set("view", "connections");
  } else if (params.get("kind") === "releases") {
    path = `${navigationPaths.formatid}/standards`;
    params.delete("kind");
  }
  return (
    <Navigate
      to={{ pathname: path, search: params.toString(), hash: location.hash }}
      replace
    />
  );
}

function workspacePage(children: ReactNode, authenticated = false) {
  const page = <WorkspaceFrame>{children}</WorkspaceFrame>;
  return authenticated ? <AdminAccess>{page}</AdminAccess> : page;
}
