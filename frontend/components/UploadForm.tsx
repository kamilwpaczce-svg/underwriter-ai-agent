"use client";

import { useRef, useState } from "react";
import { BladApi, wgrajWniosek } from "@/lib/api";
import { walidujPlik } from "@/lib/walidacja";

interface Props {
  onSukces: (id: string) => void;
}

/** Upload: wybor pliku lub przeciagnij-upusc. Walidacja klienta ORAZ wyswietlenie bledu z API. */
export default function UploadForm({ onSukces }: Props) {
  const [blad, setBlad] = useState<string | null>(null);
  const [wysylanie, setWysylanie] = useState(false);
  const [przeciagane, setPrzeciagane] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function obsluzPlik(plik: File) {
    setBlad(null);
    const walidacja = walidujPlik(plik);
    if (!walidacja.poprawny) {
      setBlad(walidacja.blad ?? "Niepoprawny plik.");
      return;
    }
    setWysylanie(true);
    try {
      const wynik = await wgrajWniosek(plik);
      onSukces(wynik.id);
    } catch (e) {
      if (e instanceof BladApi) {
        setBlad(
          typeof e.detail === "string"
            ? e.detail
            : Array.isArray(e.detail)
              ? e.detail.join("; ")
              : e.message
        );
      } else {
        setBlad("Nie udało się wgrać pliku.");
      }
    } finally {
      setWysylanie(false);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  }

  return (
    <div className="space-y-2">
      <div
        data-testid="strefa-upuszczania"
        onDragOver={(e) => {
          e.preventDefault();
          setPrzeciagane(true);
        }}
        onDragLeave={() => setPrzeciagane(false)}
        onDrop={(e) => {
          e.preventDefault();
          setPrzeciagane(false);
          const plik = e.dataTransfer.files?.[0];
          if (plik) {
            void obsluzPlik(plik);
          }
        }}
        className={`rounded border-2 border-dashed p-6 text-center text-sm ${
          przeciagane ? "border-blue-400 bg-blue-50" : "border-gray-300"
        }`}
      >
        <p className="mb-2">Przeciągnij i upuść plik (.pdf, .jpg, .jpeg, .eml) albo</p>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.eml"
          disabled={wysylanie}
          onChange={(e) => {
            const plik = e.target.files?.[0];
            if (plik) {
              void obsluzPlik(plik);
            }
          }}
        />
        {wysylanie && <p className="mt-2 text-blue-700">Wysyłanie…</p>}
      </div>
      {blad && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {blad}
        </div>
      )}
    </div>
  );
}
