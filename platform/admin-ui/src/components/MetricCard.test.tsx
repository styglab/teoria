import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricCard } from "./MetricCard";

describe("MetricCard", () => {
  it("renders a registry metric", () => {
    render(<MetricCard label="Ontologies" value={2} icon={<span>icon</span>} />);

    expect(screen.getByText("Ontologies")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });
});
