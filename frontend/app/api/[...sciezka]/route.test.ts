// @vitest-environment node
// Route handlery to kod serwerowy: srodowisko node, nie jsdom (Blob z jsdom
// nie jest akceptowany przez Response w Node 22 - wersji z obrazu i CI).
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "./route";

/**
 * Testy proxy (SPEC_ETAP6, pkt 4). Mockujemy globalny `fetch` - sprawdzamy
 * TYLKO, co proxy wysyla dalej i co zwraca klientowi, bez zadnego prawdziwego
 * polaczenia sieciowego.
 */

function kontekst(sciezka: string[]) {
  return { params: Promise.resolve({ sciezka }) };
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("GET/POST /api/[...sciezka]", () => {
  it("przekazuje GET pod API_URL_WEWNETRZNY z zachowaniem sciezki i query", async () => {
    vi.stubEnv("API_URL_WEWNETRZNY", "http://api-wewnetrzne:9000");
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));

    const request = new NextRequest(
      "http://localhost:3000/api/wnioski/123?status=NOWY"
    );
    const odpowiedz = await GET(request, kontekst(["wnioski", "123"]));

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [adresWywolania, opcje] = fetchSpy.mock.calls[0];
    expect(String(adresWywolania)).toBe(
      "http://api-wewnetrzne:9000/wnioski/123?status=NOWY"
    );
    expect(opcje?.method).toBe("GET");
    expect(odpowiedz.status).toBe(200);
    expect(odpowiedz.headers.get("content-type")).toBe("application/json");
  });

  it("domyslnie uzywa http://localhost:8000, gdy API_URL_WEWNETRZNY nie jest ustawiony", async () => {
    vi.stubEnv("API_URL_WEWNETRZNY", "");
    delete process.env.API_URL_WEWNETRZNY;
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    const request = new NextRequest("http://localhost:3000/api/zdrowie");
    await GET(request, kontekst(["zdrowie"]));

    const [adresWywolania] = fetchSpy.mock.calls[0];
    expect(String(adresWywolania)).toBe("http://localhost:8000/zdrowie");
  });

  it("gdy obecny naglowek Easy Auth, nadpisuje nim X-Uzytkownik podany przez klienta", async () => {
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 200 }));

    const request = new NextRequest("http://localhost:3000/api/wnioski/1/decyzja", {
      method: "POST",
      headers: {
        "x-ms-client-principal-name": "jan.kowalski@firma.pl",
        "x-uzytkownik": "podrobiony",
        "content-type": "application/json",
      },
      body: JSON.stringify({ decyzja: "AKCEPTACJA" }),
    });
    const odpowiedz = await POST(request, kontekst(["wnioski", "1", "decyzja"]));

    expect(odpowiedz.status).toBe(200);
    const [, opcje] = fetchSpy.mock.calls[0];
    const naglowki = opcje?.headers as Headers;
    expect(naglowki.get("X-Uzytkownik")).toBe("jan.kowalski@firma.pl");
  });

  it("bez naglowka Easy Auth przekazuje X-Uzytkownik podany przez klienta bez zmian", async () => {
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 200 }));

    const request = new NextRequest("http://localhost:3000/api/wnioski/1/decyzja", {
      method: "POST",
      headers: {
        "x-uzytkownik": "a.nowak",
        "content-type": "application/json",
      },
      body: JSON.stringify({ decyzja: "AKCEPTACJA" }),
    });
    await POST(request, kontekst(["wnioski", "1", "decyzja"]));

    const [, opcje] = fetchSpy.mock.calls[0];
    const naglowki = opcje?.headers as Headers;
    expect(naglowki.get("X-Uzytkownik")).toBe("a.nowak");
  });

  it("odrzuca naglowek Easy Auth spoza ASCII z 400, bez wywolywania API", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");

    const request = new NextRequest("http://localhost:3000/api/wnioski", {
      method: "GET",
      headers: { "x-ms-client-principal-name": "jan.kowalskió" },
    });
    const odpowiedz = await GET(request, kontekst(["wnioski"]));

    expect(odpowiedz.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("przekazuje strumien ciala przy POST z duplex: half", async () => {
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 201 }));

    const request = new NextRequest("http://localhost:3000/api/wnioski", {
      method: "POST",
      body: new Blob(["zawartosc"]),
    });
    await POST(request, kontekst(["wnioski"]));

    const [, opcje] = fetchSpy.mock.calls[0];
    expect((opcje as RequestInit & { duplex?: string } | undefined)?.duplex).toBe(
      "half"
    );
    expect(opcje?.body).toBeTruthy();
  });

  it("przepuszcza content-disposition z odpowiedzi API", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(new Blob(["bajty"]), {
        status: 200,
        headers: {
          "content-type": "application/pdf",
          "content-disposition": 'attachment; filename="wniosek.pdf"',
        },
      })
    );

    const request = new NextRequest("http://localhost:3000/api/wnioski/1/dokument");
    const odpowiedz = await GET(request, kontekst(["wnioski", "1", "dokument"]));

    expect(odpowiedz.headers.get("content-type")).toBe("application/pdf");
    expect(odpowiedz.headers.get("content-disposition")).toBe(
      'attachment; filename="wniosek.pdf"'
    );
  });

  it("zwraca 502 z detail, gdy fetch do API rzuca blad sieci", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    const request = new NextRequest("http://localhost:3000/api/zdrowie");
    const odpowiedz = await GET(request, kontekst(["zdrowie"]));

    expect(odpowiedz.status).toBe(502);
    const cialo = await odpowiedz.json();
    expect(cialo.detail).toContain("Brak polaczenia z API");
  });
});
