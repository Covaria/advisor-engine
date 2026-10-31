import { describe, expect, it } from "vitest";
import { unreachable } from "./api";

describe("unreachable", () => {
  it("names the API address and the origin that must be allowed", () => {
    const msg = unreachable("https://galtonks.onrender.com");
    expect(msg).toContain("http://localhost:8000");
    expect(msg).toContain("ALLOWED_ORIGINS includes https://galtonks.onrender.com");
  });
});
