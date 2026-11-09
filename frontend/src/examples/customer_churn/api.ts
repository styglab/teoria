import { postJson } from "../../api/http_client";

export const customerChurnApi = {
  predict: (body: Record<string, number>) =>
    postJson<{
      churn_probability: number;
      predicted_churn: boolean;
      model_version: number;
      synthetic_demo_only: boolean;
    }>("/model-operations/predict", body),
};
