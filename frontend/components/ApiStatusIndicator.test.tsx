import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ApiStatusIndicator from "./ApiStatusIndicator";

/**
 * Zastepuje test e2e "API wylaczone" (celowo pominiety - nie wolno gasic
 * zywego serwera w e2e). Mockujemy globalny fetch tak, by rzucal blad sieci,
 * identycznie jak przegladarka przy braku polaczenia z API.
 */
describe("ApiStatusIndicator", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("pokazuje stan 'sprawdzanie' od razu po zamontowaniu", () => {
    vi.spyOn(global, "fetch").mockImplementation(
      () => new Promise(() => {}) // nigdy sie nie rozstrzyga
    );
    render(<ApiStatusIndicator />);
    expect(screen.getByTestId("api-status")).toHaveTextContent(
      "Sprawdzanie połączenia z API"
    );
  });

  it("pokazuje blad z adresem API, gdy fetch rzuca blad sieci", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ApiStatusIndicator />);
    await waitFor(() => {
      expect(screen.getByTestId("api-status")).toHaveTextContent(
        "Brak połączenia z API"
      );
    });
    expect(screen.getByTestId("api-status")).toHaveTextContent("/api");
    expect(screen.getByTestId("api-status")).toHaveAttribute("role", "alert");
  });

  it("pokazuje stan OK, gdy /zdrowie odpowiada poprawnie", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 })
    );
    render(<ApiStatusIndicator />);
    await waitFor(() => {
      expect(screen.getByTestId("api-status")).toHaveTextContent("API dostępne");
    });
  });
});
