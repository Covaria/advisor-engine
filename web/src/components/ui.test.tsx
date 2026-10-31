import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComparisonTable } from "./ui";

describe("ComparisonTable", () => {
  it("shows the engine's change figure rather than computing one", () => {
    // A deliberately inconsistent row: if the table computed after - before it would
    // show +0.2; it must show the engine's -9.9.
    render(<ComparisonTable rows={[{ key: "effective_bets", label: "Effective independent bets",
                                      kind: "number", before: 1.3, after: 1.5, change: -9.9 }]} />);
    expect(screen.getByText("−9.9")).toBeTruthy();
    expect(screen.queryByText("+0.2")).toBeNull();
  });
});
