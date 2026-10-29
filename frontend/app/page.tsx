"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { pobierzListeWnioskow } from "@/lib/api";
import type { WniosekLista } from "@/lib/typy";
import { formatujDateCzas, formatujNullable, formatujTypDokumentu } from "@/lib/formatowanie";
import StatusBadge from "@/components/StatusBadge";
import ApiStatusIndicator from "@/components/ApiStatusIndicator";
import UploadForm from "@/components/UploadForm";

const STATUSY = [
  "PRZETWARZANIE",
  "CZEKA_NA_DECYZJE",
  "ZAKONCZONY",
  "INNY_DOKUMENT",
  "BLAD",
];

const INTERWAL_ODSWIEZANIA_MS = 2000;

export default function Home() {
  const router = useRouter();
  const [wnioski, setWnioski] = useState<WniosekLista[]>([]);
  const [filtr, setFiltr] = useState<string>("");
  const [ladowanie, setLadowanie] = useState(true);
  const [blad, setBlad] = useState<string | null>(null);
  const interwalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const odswiez = useCallback(async () => {
    try {
      const lista = await pobierzListeWnioskow(filtr || undefined);
      setWnioski(lista);
      setBlad(null);
    } catch {
      setBlad("Nie udało się pobrać listy wniosków.");
    } finally {
      setLadowanie(false);
    }
  }, [filtr]);

  useEffect(() => {
    // Pobranie listy przy montowaniu - setState nastepuje asynchronicznie
    // (po await fetch), nie w ramach synchronicznego ciala efektu.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void odswiez();
  }, [odswiez]);

  // Polling co 2 s TYLKO gdy na liscie jest wniosek w PRZETWARZANIU.
  useEffect(() => {
    const jestPrzetwarzany = wnioski.some((w) => w.status === "PRZETWARZANIE");
    if (jestPrzetwarzany) {
      interwalRef.current = setInterval(() => {
        void odswiez();
      }, INTERWAL_ODSWIEZANIA_MS);
    }
    return () => {
      if (interwalRef.current) {
        clearInterval(interwalRef.current);
        interwalRef.current = null;
      }
    };
  }, [wnioski, odswiez]);

  return (
    <div className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Panel underwritera</h1>
        <p className="text-sm text-gray-600">
          Mazowiecka Mutual TU S.A. — demo agenta AI do underwritingu mienia.
        </p>
        <ApiStatusIndicator />
      </header>

      <section>
        <h2 className="mb-2 text-base font-semibold">Nowy wniosek</h2>
        <UploadForm onSukces={(id) => router.push(`/wnioski/${id}`)} />
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Wnioski</h2>
          <label className="flex items-center gap-2 text-sm">
            Status:
            <select
              value={filtr}
              onChange={(e) => setFiltr(e.target.value)}
              className="rounded border border-gray-300 px-2 py-1"
            >
              <option value="">wszystkie</option>
              {STATUSY.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>

        {blad && (
          <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
            {blad}
          </div>
        )}

        {ladowanie ? (
          <p className="text-sm text-gray-500">Ładowanie…</p>
        ) : wnioski.length === 0 ? (
          <p className="text-sm text-gray-500">Brak wniosków.</p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-300 text-left text-gray-600">
                <th className="py-2 pr-4">Nazwa pliku</th>
                <th className="py-2 pr-4">Typ</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Decyzja końcowa</th>
                <th className="py-2 pr-4">Utworzono</th>
                <th className="py-2">Zakończono</th>
              </tr>
            </thead>
            <tbody>
              {wnioski.map((w) => (
                <tr
                  key={w.id}
                  onClick={() => router.push(`/wnioski/${w.id}`)}
                  className="cursor-pointer border-b border-gray-100 hover:bg-gray-50"
                >
                  <td className="py-2 pr-4">{w.nazwa_pliku}</td>
                  <td className="py-2 pr-4">{formatujTypDokumentu(w.typ_dokumentu)}</td>
                  <td className="py-2 pr-4">
                    <StatusBadge status={w.status} />
                  </td>
                  <td className="py-2 pr-4">{formatujNullable(w.decyzja_koncowa)}</td>
                  <td className="py-2 pr-4">{formatujDateCzas(w.utworzono)}</td>
                  <td className="py-2">{formatujDateCzas(w.zakonczono)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
