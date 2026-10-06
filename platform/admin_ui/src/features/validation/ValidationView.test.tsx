import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ValidationView } from "./ValidationView";

describe("ValidationView", () => {
  it("renders a valid registry state", () => {
    render(<ValidationView report={{ status: "valid", diagnostic_count: 0, diagnostics: [] }} />);
    expect(screen.getByText("Registry가 유효합니다")).toBeTruthy();
  });

  it("renders diagnostic details", () => {
    render(<ValidationView report={{
      status: "invalid",
      diagnostic_count: 1,
      diagnostics: [{
        code: "unknown_source",
        message: "Source를 찾을 수 없습니다.",
        path: "registries/sources/example.yaml",
        severity: "error",
        location: "source.id",
      }],
    }} />);
    expect(screen.getByText("unknown_source")).toBeTruthy();
    expect(screen.getByText("Source를 찾을 수 없습니다.")).toBeTruthy();
  });
});
