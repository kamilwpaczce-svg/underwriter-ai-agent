// @vitest-environment node
// Route handlery to kod serwerowy: srodowisko node, nie jsdom (Blob z jsdom
// nie jest akceptowany przez Response w Node 22 - wersji z obrazu i CI).
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

/** Testy endpointu tozsamosci proxy (SPEC_ETAP6, pkt 4). */
describe("GET /api/.ja", () => {
  it("zwraca identyfikator z naglowka Easy Auth, gdy jest obecny", async () => {
    const request = new NextRequest("http://localhost:3000/api/.ja", {
      headers: { "x-ms-client-principal-name": "jan.kowalski@firma.pl" },
    });
    const odpowiedz = await GET(request);
    expect(odpowiedz.status).toBe(200);
    expect(await odpowiedz.json()).toEqual({ identyfikator: "jan.kowalski@firma.pl" });
  });

  it("zwraca null, gdy naglowek Easy Auth jest nieobecny (dev lokalny)", async () => {
    const request = new NextRequest("http://localhost:3000/api/.ja");
    const odpowiedz = await GET(request);
    expect(await odpowiedz.json()).toEqual({ identyfikator: null });
  });

  it("zwraca null, gdy naglowek zawiera znaki spoza ASCII", async () => {
    const request = new NextRequest("http://localhost:3000/api/.ja", {
      headers: { "x-ms-client-principal-name": "jan.kowalskió" },
    });
    const odpowiedz = await GET(request);
    expect(await odpowiedz.json()).toEqual({ identyfikator: null });
  });
});
