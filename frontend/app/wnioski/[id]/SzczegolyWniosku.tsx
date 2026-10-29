"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { BladApi, pobierzAudyt, pobierzSzczegoly } from "@/lib/api";
import type { WniosekSzczegoly, ZdarzenieAudytu } from "@/lib/typy";
import { formatujDateCzas, formatujNullable } from "@/lib/formatowanie";
import { czySzkoda } from "@/lib/decyzja";
import StatusBadge from "@/components/StatusBadge";
import DocumentViewer from "@/components/DocumentViewer";
import SekcjaAnaliz from "@/components/SekcjaAnaliz";
import SekcjaOcenyPokrycia from "@/components/SekcjaOcenyPokrycia";
import DecisionForm from "@/components/DecisionForm";
import AuditTrail from "@/components/AuditTrail";

const INTERWAL_PRZETWARZANIE_MS = 1500;

function wyciagnijBladZAudytu(zdarzenia: ZdarzenieAudytu[]): string {
  const ostatni = [...zdarzenia].reverse().find((z) => z.zdarzenie === "BLAD");
  if (!ostatni || !ostatni.dane) {
    return "nieznany błąd";
  }
  const dane = ostatni.dane as { blad?: unknown; powod?: unknown };
  return String(dane.blad ?? dane.powod ?? "nieznany błąd");
}

export default function SzczegolyWniosku() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();

  const [wniosek, setWniosek] = useState<WniosekSzczegoly | null>(null);
  const [audyt, setAudyt] = useState<ZdarzenieAudytu[]>([]);
  const [blad, setBlad] = useState<string | null>(null);
  const [ladowanie, setLadowanie] = useState(true);
  const interwalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const odswiez = useCallback(async () => {
    try {
      const [szczegoly, zdarzenia] = await Promise.all([
        pobierzSzczegoly(id),
        pobierzAudyt(id),
      ]);
      setWniosek(szczegoly);
      setAudyt(zdarzenia);
      setBlad(null);
    } catch (e) {
      setBlad(
        e instanceof BladApi
          ? `Nie udało się pobrać wniosku: ${e.message}`
          : "Nie udało się pobrać wniosku."
      );
    } finally {
      setLadowanie(false);
    }
  }, [id]);

  useEffect(() => {
    // Pobranie szczegolow przy montowaniu - setState nastepuje asynchronicznie
    // (po await fetch), nie w ramach synchronicznego ciala efektu.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void odswiez();
  }, [odswiez]);

  useEffect(() => {
    if (wniosek?.status === "PRZETWARZANIE") {
      interwalRef.current = setInterval(() => {
        void odswiez();
      }, INTERWAL_PRZETWARZANIE_MS);
    }
    return () => {
      if (interwalRef.current) {
        clearInterval(interwalRef.current);
        interwalRef.current = null;
      }
    };
  }, [wniosek?.status, odswiez]);

  if (ladowanie) {
    return <div className="p-6 text-sm text-gray-500">Ładowanie…</div>;
  }

  if (blad && !wniosek) {
    return (
      <div className="p-6">
        <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {blad}
        </div>
      </div>
    );
  }

  if (!wniosek) {
    return <div className="p-6 text-sm text-gray-500">Wniosek nie istnieje.</div>;
  }

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 space-y-4 p-6">
      <button
        type="button"
        onClick={() => router.push("/")}
        className="text-sm text-blue-700 underline"
      >
        ← Wróć do listy
      </button>

      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{wniosek.nazwa_pliku}</h1>
        <StatusBadge status={wniosek.status} />
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <DocumentViewer id={wniosek.id} typMime={wniosek.typ_mime} nazwaPliku={wniosek.nazwa_pliku} />
        </div>

        <div className="space-y-4">
          {wniosek.status === "PRZETWARZANIE" && (
            <div className="rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900">
              Agent analizuje dokument…
            </div>
          )}

          {wniosek.status === "INNY_DOKUMENT" && (
            <div className="rounded border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-800">
              Ten dokument nie jest wnioskiem ubezpieczeniowym. Brak dalszej analizy i decyzji.
            </div>
          )}

          {wniosek.status === "BLAD" && (
            <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
              <p className="font-semibold">Wystąpił błąd podczas przetwarzania wniosku.</p>
              <p>{wyciagnijBladZAudytu(audyt)}</p>
            </div>
          )}

          {czySzkoda(wniosek.podsumowanie) ? (
            <SekcjaOcenyPokrycia podsumowanie={wniosek.podsumowanie} />
          ) : (
            wniosek.podsumowanie && <SekcjaAnaliz podsumowanie={wniosek.podsumowanie} wniosek={wniosek} />
          )}

          {wniosek.status === "CZEKA_NA_DECYZJE" && (
            <DecisionForm wniosek={wniosek} onPoDecyzji={() => void odswiez()} />
          )}

          {wniosek.status === "ZAKONCZONY" && (
            <div className="space-y-1 rounded border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-900">
              <p>
                <span className="font-medium">Decyzja końcowa:</span>{" "}
                {formatujNullable(wniosek.decyzja_koncowa)}
              </p>
              <p>
                <span className="font-medium">Zatwierdził:</span>{" "}
                {formatujNullable(wniosek.zatwierdzil)}
              </p>
              <p>
                <span className="font-medium">Komentarz:</span>{" "}
                {formatujNullable(wniosek.komentarz)}
              </p>
              <p>
                <span className="font-medium">Zakończono:</span>{" "}
                {formatujDateCzas(wniosek.zakonczono)}
              </p>
            </div>
          )}
        </div>
      </div>

      <AuditTrail zdarzenia={audyt} />
    </div>
  );
}
