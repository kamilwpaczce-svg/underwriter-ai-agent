import { NextRequest } from "next/server";

/**
 * Proxy `/api/*` -> `API_URL_WEWNETRZNY` (domyslnie `http://localhost:8000`), czytany
 * W CZASIE DZIALANIA (nie przy buildzie) - patrz SPEC_ETAP6.md, pkt 4. W Azure
 * przegladarka mowi wylacznie do wlasnego originu (`uw-web`); `uw-api` nie ma adresu
 * w internecie i nie potrzebuje wlasnego CORS ani uwierzytelnienia.
 *
 * X-Uzytkownik: Easy Auth (Container Apps) ustawia naglowek `x-ms-client-principal-name`
 * i NADPISUJE kazda wartosc podana przez klienta (ochrona przed podrobieniem tozsamosci) -
 * gdy jest obecny, proxy wysyla jego wartosc do API jako `X-Uzytkownik` (musi byc ASCII,
 * inaczej 400). Bez Easy Auth (dev lokalny, brak tego naglowka) proxy przekazuje
 * `X-Uzytkownik` podany wprost przez klienta, bez zmian.
 *
 * Strumien ciala: `request.body` to `ReadableStream` (multipart upload dziala bez
 * buforowania calego pliku w pamieci Next.js) - fetch w Node wymaga `duplex: "half"`,
 * gdy body jest strumieniem.
 */

const ADRES_API_WEWNETRZNY_DOMYSLNY = "http://localhost:8000";

type KontekstTrasy = { params: Promise<{ sciezka: string[] }> };

function czyAscii(wartosc: string): boolean {
   
  return /^[\x00-\x7F]*$/.test(wartosc);
}

async function przekazDoApi(request: NextRequest, context: KontekstTrasy): Promise<Response> {
  const { sciezka } = await context.params;
  const bazowyAdres = process.env.API_URL_WEWNETRZNY ?? ADRES_API_WEWNETRZNY_DOMYSLNY;
  const adresDocelowy = new URL(`/${sciezka.join("/")}`, bazowyAdres);
  adresDocelowy.search = request.nextUrl.search;

  const naglowki = new Headers();
  const typTresci = request.headers.get("content-type");
  if (typTresci) {
    naglowki.set("content-type", typTresci);
  }

  const identyfikatorEasyAuth = request.headers.get("x-ms-client-principal-name");
  if (identyfikatorEasyAuth !== null) {
    if (!czyAscii(identyfikatorEasyAuth)) {
      return Response.json(
        { detail: "Naglowek x-ms-client-principal-name musi byc czystym ASCII." },
        { status: 400 }
      );
    }
    naglowki.set("X-Uzytkownik", identyfikatorEasyAuth);
  } else {
    const identyfikatorKlienta = request.headers.get("x-uzytkownik");
    if (identyfikatorKlienta !== null) {
      naglowki.set("X-Uzytkownik", identyfikatorKlienta);
    }
  }

  const maCialo = request.method !== "GET" && request.method !== "HEAD";
  const inicjator: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers: naglowki,
    body: maCialo ? request.body : undefined,
  };
  if (maCialo) {
    inicjator.duplex = "half";
  }

  let odpowiedzApi: Response;
  try {
    odpowiedzApi = await fetch(adresDocelowy, inicjator);
  } catch (e) {
    return Response.json(
      { detail: `Brak polaczenia z API (${bazowyAdres}): ${e instanceof Error ? e.message : String(e)}` },
      { status: 502 }
    );
  }

  const odpowiedzNaglowki = new Headers();
  for (const nazwa of ["content-type", "content-disposition"]) {
    const wartosc = odpowiedzApi.headers.get(nazwa);
    if (wartosc) {
      odpowiedzNaglowki.set(nazwa, wartosc);
    }
  }

  return new Response(odpowiedzApi.body, {
    status: odpowiedzApi.status,
    headers: odpowiedzNaglowki,
  });
}

export async function GET(request: NextRequest, context: KontekstTrasy): Promise<Response> {
  return przekazDoApi(request, context);
}

export async function POST(request: NextRequest, context: KontekstTrasy): Promise<Response> {
  return przekazDoApi(request, context);
}
