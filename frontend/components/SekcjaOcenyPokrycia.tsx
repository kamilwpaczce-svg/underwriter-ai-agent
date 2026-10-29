import type { PodsumowanieSzkody, RyzykoSzkody, ZdjecieSzkody } from "@/lib/typy";
import { formatujKwote, formatujNullable } from "@/lib/formatowanie";

interface Props {
  podsumowanie: PodsumowanieSzkody;
}

// Nazwy cech modelu ryzyka (ryzyko/cechy.py) po ludzku; nieznana cecha zostaje pod swoja nazwa.
const NAZWY_CECH: Record<string, string> = {
  suma_ubezpieczenia: "suma ubezpieczenia",
  udzial_kwoty: "udział kwoty szkody w sumie ubezpieczenia",
  dni_do_zgloszenia: "dni do zgłoszenia",
  dni_od_poczatku_polisy: "dni od początku polisy",
  rodzaj_mienia: "rodzaj mienia",
  liczba_zalacznikow: "liczba załączników",
  szkody_3_lata: "szkody w ostatnich 3 latach",
};

/**
 * Wiersz "Sygnał ryzyka" (Etap 15). Trzy stany: OK (wynik, wersja modelu, glowne cechy),
 * BRAK_DANYCH (brak polisy lub pol), MODEL_NIEDOSTEPNY. Zawsze z dopiskiem, ze to material
 * do weryfikacji, nie decyzja. Brak klucza `ryzyko` (stare podsumowania) = brak wiersza.
 */
function SygnalRyzyka({ ryzyko }: { ryzyko: RyzykoSzkody | undefined }) {
  if (!ryzyko) return null;
  let tekst: string;
  if (ryzyko.status === "OK" && typeof ryzyko.wynik === "number") {
    const wynik = String(ryzyko.wynik).replace(".", ",");
    tekst = `${wynik} (model ${ryzyko.wersja ?? "?"}) — do weryfikacji likwidatora`;
  } else if (ryzyko.status === "BRAK_DANYCH") {
    tekst = "brak danych (brak polisy lub pól)";
  } else {
    tekst = "model niedostępny";
  }
  const cechy = ryzyko.status === "OK" ? (ryzyko.glowne_cechy ?? []) : [];
  return (
    <div className="rounded border border-gray-300 p-3 text-sm" data-testid="sygnal-ryzyka">
      <p>
        <span className="font-medium">Sygnał ryzyka:</span> {tekst}
      </p>
      {cechy.length > 0 && (
        <p className="text-gray-700" data-testid="sygnal-ryzyka-cechy">
          <span className="font-medium">Główne czynniki (przybliżenie, nie wyjaśnienie modelu):</span>{" "}
          {cechy.map((cecha) => NAZWY_CECH[cecha] ?? cecha).join(", ")}
        </p>
      )}
    </div>
  );
}

// Rodzaje zdarzen z modelu vision (agent/schematy.py: RodzajZdarzenia) po ludzku; nieznany zostaje pod swoja nazwa.
const NAZWY_RODZAJOW: Record<string, string> = {
  pozar: "pożar",
  zalanie: "zalanie",
  przepiecie: "przepięcie",
  kradziez_wlamanie: "kradzież lub włamanie",
  huragan_wiatr: "huragan lub wiatr",
  korozja_zawilgocenie: "korozja lub zawilgocenie",
  awaria_wewnetrzna: "awaria wewnętrzna",
  inne: "inne",
};

const NAZWY_DLUGOTRWALOSCI: Record<string, string> = {
  NAGLE: "nagłe",
  DLUGOTRWALE: "długotrwałe",
  NIEOKRESLONE: "charakter nieokreślony",
};

// Kody powodow (agent/zdjecia.py, agent/wezly_szkody.py) po ludzku; nieznany kod zostaje bez zmian.
const NAZWY_POWODOW: Record<string, string> = {
  niska_pewnosc: "niska pewność modelu",
  brak_widocznej_szkody: "na zdjęciu nie widać szkody",
  rodzaj_inne: "model nie rozpoznał rodzaju zdarzenia",
  kategorie_pokrewne: "rodzaje zdarzeń pokrewne",
  przyczyna_nierozpoznana: "nie rozpoznano zgłoszonej przyczyny",
  nieobslugiwany_typ: "nieobsługiwany typ pliku",
  plik_nie_istnieje: "plik nie istnieje",
  plik_za_duzy: "plik za duży",
  plik_pusty: "plik pusty",
  niezgodny_naglowek: "zawartość pliku nie zgadza się z jego rozszerzeniem",
  blad_odczytu: "błąd odczytu pliku",
  pominiete: "pominięto przy podejrzanych instrukcjach w dokumencie",
  pominieto_kolejne_zdjecia: "przeanalizowano tylko pierwsze zdjęcie",
};

function opisPowodow(powody: string[] | undefined): string {
  return (powody ?? []).map((powod) => NAZWY_POWODOW[powod] ?? powod).join(", ");
}

/**
 * Wiersz "Zdjęcie" (Etap 23). Zawsze z dopiskiem, ze to material do weryfikacji, nie decyzja
 * (decyzja szkody zdjecia nie uwzglednia). Status OK: rodzaj, pewnosc modelu, charakter zdarzenia
 * i zgodnosc ze zgloszeniem (liczona kodem): ZGODNE / NIEZGODNE (zgloszono: ...) / NIEUSTALONA.
 * Osobna linia, gdy sa oznaki dlugotrwalosci przy zgloszeniu naglego zdarzenia. Pozostale statusy
 * (BRAK_ZDJECIA, MODEL_NIEDOSTEPNY, BLAD_ODCZYTU) to tekst, nie puste miejsce. Brak klucza `zdjecie`
 * (stare podsumowania) = brak wiersza.
 */
function SygnalZdjecia({ zdjecie }: { zdjecie: ZdjecieSzkody | undefined }) {
  if (!zdjecie) return null;
  const powody = opisPowodow(zdjecie.powody);
  let tekst: string;
  let oznaki: string[] = [];
  if (zdjecie.status === "OK" && zdjecie.ocena) {
    const { ocena } = zdjecie;
    const rodzaj = NAZWY_RODZAJOW[ocena.rodzaj_zdarzenia] ?? ocena.rodzaj_zdarzenia;
    const pewnosc = ocena.pewnosc.toFixed(2).replace(".", ",");
    const charakter = NAZWY_DLUGOTRWALOSCI[ocena.dlugotrwalosc] ?? ocena.dlugotrwalosc;
    const opis = `${rodzaj} (pewność modelu ${pewnosc}), ${charakter}`;
    if (zdjecie.zgodnosc_rodzaju === "ZGODNE") {
      tekst = `${opis} — zgodne ze zgłoszeniem`;
    } else if (zdjecie.zgodnosc_rodzaju === "NIEZGODNE") {
      const zgloszono = zdjecie.kategoria_zgloszona
        ? (NAZWY_RODZAJOW[zdjecie.kategoria_zgloszona] ?? zdjecie.kategoria_zgloszona)
        : "?";
      tekst = `${opis} — NIEZGODNE ze zgłoszeniem (zgłoszono: ${zgloszono}) — do weryfikacji likwidatora`;
    } else {
      tekst = `${opis} — zgodności ze zgłoszeniem nie ustalono${powody ? ` (${powody})` : ""}`;
    }
    if (zdjecie.sygnal_dlugotrwalosci) oznaki = ocena.oznaki ?? [];
  } else if (zdjecie.status === "BRAK_ZDJECIA") {
    tekst = powody ? `nie przeanalizowano (${powody})` : "nie dołączono zdjęcia";
  } else if (zdjecie.status === "MODEL_NIEDOSTEPNY") {
    tekst = `nie przeanalizowano — model niedostępny${powody ? ` (${powody})` : ""}`;
  } else if (zdjecie.status === "BLAD_ODCZYTU") {
    tekst = `nie udało się odczytać pliku${powody ? ` (${powody})` : ""}`;
  } else {
    tekst = "brak danych ze zdjęcia";
  }
  return (
    <div className="rounded border border-gray-300 p-3 text-sm" data-testid="sygnal-zdjecia">
      <p>
        <span className="font-medium">Zdjęcie:</span> {tekst}
      </p>
      {zdjecie.status === "OK" && zdjecie.sygnal_dlugotrwalosci && (
        <p className="text-orange-900" data-testid="sygnal-zdjecia-dlugotrwalosc">
          Oznaki długotrwałości{oznaki.length > 0 ? ` (${oznaki.join(", ")})` : ""} przy zgłoszeniu nagłego
          zdarzenia — do weryfikacji likwidatora
        </p>
      )}
    </div>
  );
}

/**
 * Sekcja "Ocena pokrycia" dla zgloszenia szkody (Etap 10): decyzja po regulach,
 * wynik sprawdzenia polisy, cytowane ustepy OWU z pelna trescia, brakujace
 * dokumenty, wynik kontroli cytatow. Komponent czysto prezentacyjny (bez fetch).
 */
export default function SekcjaOcenyPokrycia({ podsumowanie }: Props) {
  const {
    blad,
    podejrzane_instrukcje,
    pola,
    wynik_polisy,
    decyzja,
    powody_decyzji,
    decyzja_llm,
    cytaty,
    brakujace_dokumenty,
    kontrola_cytatow,
    dodatkowe_zapytanie,
    ryzyko,
    zdjecie,
  } = podsumowanie;

  return (
    <div className="space-y-4">
      {blad && (
        <div
          className="rounded border-2 border-red-500 bg-red-100 px-3 py-2 text-sm text-red-900"
          role="alert"
          data-testid="blad-agenta"
        >
          <span className="font-semibold">Błąd agenta:</span> {blad}
        </div>
      )}

      {decyzja_llm && (
        <div
          className="rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900"
          data-testid="baner-ai"
        >
          Ocena pokrycia wygenerowana przez model AI na podstawie OWU. Decyzję podejmuje likwidator.
        </div>
      )}

      {podejrzane_instrukcje && (
        <div
          className="rounded border-2 border-red-500 bg-red-100 px-3 py-2 text-sm font-semibold text-red-900"
          role="alert"
          data-testid="baner-podejrzane-instrukcje"
        >
          Uwaga: dokument zawiera treść przypominającą polecenia dla modelu AI
          (próba wstrzyknięcia poleceń). Zgłoszenie skierowano do człowieka bez oceny modelu.
        </div>
      )}

      <h2 className="text-base font-semibold">Ocena pokrycia</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded border border-gray-300 p-3 text-sm" data-testid="decyzja-szkody">
          <h3 className="mb-2 font-semibold">Rekomendacja (reguły + model)</h3>
          <p>
            <span className="font-medium">Decyzja:</span> {decyzja}
          </p>
          <p>
            <span className="font-medium">Powody:</span> {powody_decyzji.join(", ")}
          </p>
          <p>
            <span className="font-medium">Ocena modelu AI:</span> {formatujNullable(decyzja_llm)}
          </p>
        </div>

        <div className="rounded border border-gray-300 p-3 text-sm" data-testid="wynik-polisy">
          <h3 className="mb-2 font-semibold">Sprawdzenie polisy</h3>
          {wynik_polisy ? (
            <>
              <p>
                <span className="font-medium">Kody:</span>{" "}
                {wynik_polisy.kody.length > 0 ? wynik_polisy.kody.join(", ") : "brak uwag"}
              </p>
              <p>
                <span className="font-medium">Suma ubezpieczenia:</span>{" "}
                {formatujKwote(wynik_polisy.suma_ubezpieczenia)}
              </p>
              {wynik_polisy.opis.length > 0 && (
                <ul className="list-disc pl-5">
                  {wynik_polisy.opis.map((opis, indeks) => (
                    <li key={indeks}>{opis}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className="text-gray-500">Polisy nie sprawdzono.</p>
          )}
        </div>
      </div>

      <SygnalRyzyka ryzyko={ryzyko} />

      <SygnalZdjecia zdjecie={zdjecie} />

      {pola && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm" data-testid="pola-szkody">
          <dt className="font-medium">Nr polisy</dt>
          <dd>{formatujNullable(pola.nr_polisy)}</dd>
          <dt className="font-medium">Data zdarzenia</dt>
          <dd>{formatujNullable(pola.data_zdarzenia)}</dd>
          <dt className="font-medium">Rodzaj mienia</dt>
          <dd>{formatujNullable(pola.rodzaj_mienia)}</dd>
          <dt className="font-medium">Szacowana kwota</dt>
          <dd>{formatujKwote(pola.szacowana_kwota)}</dd>
          <dt className="font-medium">Przyczyna</dt>
          <dd>{formatujNullable(pola.przyczyna)}</dd>
        </dl>
      )}

      {kontrola_cytatow && !kontrola_cytatow.ok && (
        <div
          className="rounded border-2 border-orange-400 bg-orange-50 px-3 py-2 text-sm text-orange-900"
          role="alert"
          data-testid="kontrola-cytatow-odrzucila"
        >
          <span className="font-semibold">Kontrola cytatów odrzuciła ocenę modelu:</span>{" "}
          {kontrola_cytatow.powod}
        </div>
      )}

      <div data-testid="cytaty-owu">
        <h3 className="mb-2 text-sm font-semibold">Cytowane ustępy OWU</h3>
        {cytaty.length === 0 ? (
          <p className="text-sm text-gray-500">Model nie wskazał ustępów OWU.</p>
        ) : (
          <ul className="space-y-3">
            {cytaty.map((cytat) => (
              <li key={`${cytat.paragraf}-${cytat.ustep}`} className="rounded border border-gray-300 p-3 text-sm">
                <p className="font-medium">
                  {cytat.paragraf} ust. {cytat.ustep}
                </p>
                <p className="text-gray-700">{cytat.uzasadnienie}</p>
                {cytat.tresc ? (
                  <blockquote className="mt-2 border-l-4 border-gray-300 pl-3 whitespace-pre-line text-gray-900">
                    {cytat.tresc}
                  </blockquote>
                ) : (
                  <p className="mt-2 text-red-700" data-testid="cytat-bez-tresci">
                    Tego ustępu nie było wśród pobranych fragmentów OWU.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {brakujace_dokumenty.length > 0 && (
        <div
          className="rounded border border-yellow-400 bg-yellow-50 px-3 py-2 text-sm text-yellow-900"
          data-testid="brakujace-dokumenty"
        >
          <p className="mb-1 font-semibold">Brakujące dokumenty:</p>
          <ul className="list-disc pl-5">
            {brakujace_dokumenty.map((dokument, indeks) => (
              <li key={indeks}>{dokument}</li>
            ))}
          </ul>
        </div>
      )}

      {dodatkowe_zapytanie && (
        <p className="text-sm text-gray-600" data-testid="dodatkowe-zapytanie">
          Model dopytał OWU: „{dodatkowe_zapytanie}”.
        </p>
      )}
    </div>
  );
}
