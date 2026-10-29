"use client";

import { useEffect, useState } from "react";
import { BladApi, pobierzTozsamosc, wyslijDecyzje } from "@/lib/api";
import { czySzkoda, czyWymaganyKomentarz, opcjeDecyzji } from "@/lib/decyzja";
import { walidujIdentyfikator } from "@/lib/walidacja";
import type { Decyzja, WniosekSzczegoly } from "@/lib/typy";

const KLUCZ_LOCALSTORAGE = "underwriter_identyfikator";

interface Props {
  wniosek: WniosekSzczegoly;
  /** Wywolywane po kazdej odpowiedzi serwera, ktora zmienila stan wniosku (sukces albo 409). */
  onPoDecyzji: () => void;
}

export default function DecisionForm({ wniosek, onPoDecyzji }: Props) {
  const [decyzja, setDecyzja] = useState<Decyzja | null>(null);
  const [identyfikator, setIdentyfikator] = useState("");
  const [identyfikatorZablokowany, setIdentyfikatorZablokowany] = useState(false);
  const [komentarz, setKomentarz] = useState("");
  const [wysylanie, setWysylanie] = useState(false);
  const [bladSerwera, setBladSerwera] = useState<string | null>(null);

  useEffect(() => {
    let aktywny = true;
    // Najpierw tozsamosc widziana przez proxy (Easy Auth w Azure) - gdy jest obecna,
    // identyfikator z formularza i tak zostalby zignorowany przez proxy, wiec pole
    // ma byc wypelnione i zablokowane. Bez Easy Auth (dev lokalny; endpoint
    // niedostepny w testach bez mocka fetch) - zapamietany identyfikator z localStorage,
    // dokladnie jak dotychczas.
    (async () => {
      let identyfikatorZEasyAuth: string | null = null;
      try {
        identyfikatorZEasyAuth = (await pobierzTozsamosc()).identyfikator;
      } catch {
        identyfikatorZEasyAuth = null;
      }
      if (!aktywny) {
        return;
      }
      if (identyfikatorZEasyAuth) {
         
        setIdentyfikator(identyfikatorZEasyAuth);
         
        setIdentyfikatorZablokowany(true);
        return;
      }
      const zapamietany = window.localStorage.getItem(KLUCZ_LOCALSTORAGE);
      if (zapamietany) {
         
        setIdentyfikator(zapamietany);
      }
    })();
    return () => {
      aktywny = false;
    };
  }, []);

  const podsumowanie = wniosek.podsumowanie;
  // Szkoda: serwer porownuje wybor tylko z decyzja po regulach (`podsumowanie.decyzja`),
  // patrz api/trasy.py - ta sama wartosc trafia w oba argumenty.
  const [rekomendacjaLlm, decyzjaSilnika] = czySzkoda(podsumowanie)
    ? [podsumowanie.decyzja, podsumowanie.decyzja]
    : [podsumowanie?.rekomendacja?.decyzja ?? null, podsumowanie?.decyzja_silnika?.decyzja ?? null];
  const opcje = opcjeDecyzji(podsumowanie?.typ_dokumentu);
  const wymaganyKomentarz = czyWymaganyKomentarz(decyzja, rekomendacjaLlm, decyzjaSilnika);

  // Tozsamosc z Easy Auth (zwykle e-mail z "@") ustala serwer, nie uzytkownik - regex
  // dotyczy tylko recznego wpisu. Proxy i tak nadpisuje X-Uzytkownik tym naglowkiem.
  const walidacjaIdentyfikatora = identyfikatorZablokowany
    ? { poprawny: true }
    : walidujIdentyfikator(identyfikator);
  const komentarzOk = !wymaganyKomentarz || komentarz.trim().length > 0;
  const formularzPoprawny =
    decyzja !== null && walidacjaIdentyfikatora.poprawny && komentarzOk;

  async function obsluzWyslanie() {
    if (!decyzja || !formularzPoprawny || wysylanie) {
      return;
    }
    setWysylanie(true);
    setBladSerwera(null);
    try {
      if (!identyfikatorZablokowany) {
        window.localStorage.setItem(KLUCZ_LOCALSTORAGE, identyfikator);
      }
      await wyslijDecyzje(wniosek.id, decyzja, komentarz.trim() || null, identyfikator);
      onPoDecyzji();
    } catch (e) {
      if (e instanceof BladApi) {
        if (e.status === 409) {
          setBladSerwera(
            `${typeof e.detail === "string" ? e.detail : "Status wniosku zmienił się."} Dane zostały odświeżone.`
          );
          onPoDecyzji();
        } else if (e.status === 422) {
          setBladSerwera(typeof e.detail === "string" ? e.detail : "Niepoprawne dane.");
        } else {
          setBladSerwera("Wystąpił błąd serwera. Spróbuj ponownie później.");
        }
      } else {
        setBladSerwera("Wystąpił nieoczekiwany błąd.");
      }
    } finally {
      setWysylanie(false);
    }
  }

  return (
    <div className="space-y-4 rounded border border-gray-300 p-4">
      <h3 className="text-base font-semibold">Decyzja underwritera</h3>

      <fieldset className="space-y-1">
        <legend className="mb-1 text-sm font-medium">Wybierz decyzję</legend>
        {opcje.map((opcja) => (
          <label key={opcja.wartosc} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="decyzja"
              value={opcja.wartosc}
              checked={decyzja === opcja.wartosc}
              onChange={() => setDecyzja(opcja.wartosc)}
            />
            {opcja.etykieta}
          </label>
        ))}
      </fieldset>

      <div>
        <label htmlFor="identyfikator" className="mb-1 block text-sm font-medium">
          Twój identyfikator
        </label>
        <input
          id="identyfikator"
          type="text"
          value={identyfikator}
          onChange={(e) => setIdentyfikator(e.target.value)}
          placeholder="np. a.nowak"
          disabled={identyfikatorZablokowany}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-500"
        />
        {identyfikatorZablokowany && (
          <p className="mt-1 text-sm text-gray-500">
            Tożsamość ustalona przez logowanie — pole jest zablokowane.
          </p>
        )}
        {!identyfikatorZablokowany && identyfikator.length > 0 && !walidacjaIdentyfikatora.poprawny && (
          <p className="mt-1 text-sm text-red-700">{walidacjaIdentyfikatora.blad}</p>
        )}
      </div>

      <div>
        <label htmlFor="komentarz" className="mb-1 block text-sm font-medium">
          {wymaganyKomentarz
            ? "Komentarz (wymagany — odchodzisz od rekomendacji)"
            : "Komentarz (opcjonalny)"}
        </label>
        <textarea
          id="komentarz"
          value={komentarz}
          onChange={(e) => setKomentarz(e.target.value)}
          rows={3}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </div>

      {bladSerwera && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {bladSerwera}
        </div>
      )}

      <button
        type="button"
        onClick={obsluzWyslanie}
        disabled={!formularzPoprawny || wysylanie}
        className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500"
      >
        {wysylanie ? "Wysyłanie…" : "Zatwierdź decyzję"}
      </button>
    </div>
  );
}
