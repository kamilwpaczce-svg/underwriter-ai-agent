"""CLI ewaluacji agenta: uruchamia graf na przypadkach dane/wnioski, porownuje
z dane/oczekiwane, drukuje tabele ASCII i zapisuje wyniki do ewaluacja/wyniki/.

Przyklady:
    python ewaluacja/uruchom.py                        # wszystkie 14 przypadkow, Gemini
    python ewaluacja/uruchom.py --przypadki W01,W05     # wybrane przypadki
    python ewaluacja/uruchom.py --atrapa                # bez sieci, dane z dane/oczekiwane
    python ewaluacja/uruchom.py --atrapa --modul szkody # Etap 10: 12 zgloszen szkod, BM25 lokalnie
    python ewaluacja/uruchom.py --atrapa --modul szkody --zdjecia   # Etap 23: ze zdjeciami z dane/zdjecia_szkod
    python ewaluacja/uruchom.py --atrapa --wariant wieloagentowy    # Etap 24: supervisor + 3 agenci (domyslnie `jeden`)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent.decyzje_szkody import podsumowanie_szkody  # noqa: E402
from agent.graf import WARIANTY_GRAFU, wybierz_graf  # noqa: E402
from agent.model import BrakKluczaAPI, ModelAgenta, ModelGemini  # noqa: E402
from agent.model_azure import BrakKonfiguracjiAzure, ModelAzure  # noqa: E402
from agent.model_vllm import BrakKonfiguracjiVLLM, ModelVLLM  # noqa: E402
from agent.ocr_azure import liczniki_ocr, resetuj_liczniki_ocr  # noqa: E402
from ewaluacja.atrapa import ModelAtrapa  # noqa: E402
from ewaluacja.mlflow_log import zaloguj_przebieg  # noqa: E402
from ewaluacja.porownanie import porownaj_przypadek, przypadek_w_pelni_zgodny  # noqa: E402
from ewaluacja.szkody import (  # noqa: E402
    KLUCZE_RAG,
    metryki_szkod,
    porownaj_szkode,
    przypadek_szkody_zgodny,
    raport_md_szkod,
    tabela_ascii_szkod,
    tabela_szkod_mlflow,
    uruchom_szkode,
    wczytaj_oczekiwany_szkody,
    wszystkie_id_szkod,
)
from ewaluacja.trasy_oczekiwane import pola_wariantu  # noqa: E402
from rag.azure_search import BrakKonfiguracjiWyszukiwarki, zbuduj_wyszukiwarke  # noqa: E402
from rag.fragmenty import wersja_owu  # noqa: E402
from rag.wyszukiwarka import TOP_K, WyszukiwarkaLokalna  # noqa: E402

DANE_DIR = ROOT / "dane"
WNIOSKI_DIR = DANE_DIR / "wnioski"
OCZEKIWANE_DIR = DANE_DIR / "oczekiwane"
WYTYCZNE_SCIEZKA = ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml"
WYNIKI_DIR = Path(__file__).resolve().parent / "wyniki"

LIMIT_LACZNY_WYWOLAN = 100
# Bezpiecznik kosztowy: tokeny wejscia + wyjscia (z mysleniem) lacznie na przebieg.
LIMIT_TOKENOW_DOMYSLNY = 400_000

# Etap 5 - cennik gpt-5-mini (Azure OpenAI), cennik do weryfikacji - w repo brak
# oficjalnego, zaktualizowanego cennika Azure dla tego wdrozenia; wartosci orientacyjne.
CENA_GPT5_MINI_WE_USD_NA_MILION = 0.25
CENA_GPT5_MINI_WY_USD_NA_MILION = 2.00

NAGLOWKI_TABELI = [
    "ID", "Typ", "Pola", "DecyzjaLLM", "RegulyLLM", "SilnikNaPolachLLM", "Podejrzane", "Czas[ms]",
]


def _wszystkie_id_przypadkow() -> list[str]:
    return sorted(p.stem for p in OCZEKIWANE_DIR.glob("*.json"))


def _znajdz_plik_wniosku(id_przypadku: str) -> Path:
    kandydaci = sorted(p for p in WNIOSKI_DIR.glob(f"{id_przypadku}.*"))
    if not kandydaci:
        raise FileNotFoundError(f"Brak pliku wniosku dla '{id_przypadku}' w {WNIOSKI_DIR}")
    return kandydaci[0]


def _wczytaj_oczekiwany(id_przypadku: str) -> dict:
    with open(OCZEKIWANE_DIR / f"{id_przypadku}.json", "r", encoding="utf-8") as plik:
        return json.load(plik)


def _zbuduj_model(
    uzyj_atrapy: bool,
    nazwa_modelu: str | None,
    myslenie: str | None = None,
    dostawca: str = "gemini",
    reasoning: str | None = None,
) -> ModelAgenta:
    if uzyj_atrapy:
        return ModelAtrapa(OCZEKIWANE_DIR)
    if dostawca == "azure":
        return ModelAzure(deployment=nazwa_modelu, reasoning_effort=reasoning)
    if dostawca == "vllm":
        # Konfiguracja (base_url/klucz/metoda structured output) wylacznie ze zmiennych
        # srodowiskowych VLLM_* - patrz agent/model_vllm.py. `reasoning` (Azure) i
        # `myslenie` (Gemini) nie maja odpowiednika dla vLLM, ignorowane.
        return ModelVLLM(model=nazwa_modelu)
    return ModelGemini(model=nazwa_modelu, myslenie=myslenie)


def _pola_metadanych_wariantu(wariant: str, model: ModelAgenta) -> dict:
    """Etap 24: pola `metadane` wspolne dla obu modulow. `reasoning` tylko dla Azure (poziom nie byl
    dotad zapisywany ani w nazwie pliku, ani w metadanych - nie dalo sie go odczytac po fakcie)."""
    pola: dict = {"wariant": wariant}
    if isinstance(model, ModelAzure) and not isinstance(model, ModelVLLM):
        pola["reasoning"] = getattr(model, "myslenie", None)
    return pola


def _sufiks_wariantu(wariant: str) -> str:
    """Wariant `jeden` zachowuje dotychczasowe nazwy plikow; inne dostaja sufiks (bez kolizji w jednej minucie)."""
    return "" if wariant == "jeden" else f"_{wariant}"


def _metadane_licznikow(wiersze: list[dict]) -> dict:
    """`wywolania_llm_laczne` = agenci + supervisor (porownywalne miedzy wariantami); skladniki osobno."""
    agenci = sum(w["_wywolania_llm"] for w in wiersze)
    supervisor = sum(w["wywolania_supervisora"] for w in wiersze)
    return {
        "wywolania_llm_laczne": agenci + supervisor,
        "wywolania_llm_agenci_laczne": agenci,
        "wywolania_supervisora_laczne": supervisor,
        "korekty_supervisora_laczne": sum(w["korekty_supervisora"] for w in wiersze),
        "trasa_zgodna_laczne": sum(1 for w in wiersze if w["trasa_zgodna"]),
    }


def _uruchom_przypadek(graf, model: ModelAgenta, id_przypadku: str) -> dict:
    if hasattr(model, "ustaw_przypadek"):
        model.ustaw_przypadek(id_przypadku)

    plik = _znajdz_plik_wniosku(id_przypadku)
    config = {"configurable": {"thread_id": f"ewaluacja-{id_przypadku}-{uuid.uuid4().hex[:8]}"}}

    start = time.monotonic()
    stan = graf.invoke({"plik": str(plik), "wywolania_llm": 0, "log": []}, config)

    if "__interrupt__" in stan:
        rekomendacja = stan.get("rekomendacja") or {}
        decyzja_do_zatwierdzenia = rekomendacja.get("decyzja") or "SKIEROWANIE"
        stan = graf.invoke(
            Command(resume={"decyzja": decyzja_do_zatwierdzenia, "kto": "ewaluacja-automat"}),
            config,
        )

    stan["_czas_ms"] = (time.monotonic() - start) * 1000
    return stan


def _tabela_ascii(wiersze: list[dict]) -> str:
    linie = [" | ".join(NAGLOWKI_TABELI)]
    for w in wiersze:
        linie.append(
            " | ".join(
                [
                    w["id"],
                    "OK" if w["typ_dokumentu_ok"] else "BLAD",
                    f"{w['pola_trafione']}/{w['pola_wszystkie']}",
                    "OK" if w["decyzja_llm_ok"] else f"BLAD({w['decyzja_llm_otrzymana']}!={w['decyzja_llm_oczekiwana']})",
                    "OK" if w["reguly_llm_ok"] else "BLAD",
                    "OK" if w["decyzja_silnika_na_polach_llm_ok"] else "BLAD",
                    "OK" if w["podejrzane_instrukcje_ok"] else "BLAD",
                    f"{w.get('_czas_ms', 0.0):.0f}",
                ]
            )
        )
    return "\n".join(linie)


def _bezpieczna_nazwa_pliku(tekst: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", tekst)


def _zapisz_wyniki(
    nazwa_modelu: str, wiersze: list[dict], metadane: dict, sufiks_pliku: str = ""
) -> tuple[Path, Path]:
    WYNIKI_DIR.mkdir(parents=True, exist_ok=True)
    znacznik_czasu = time.strftime("%Y%m%d-%H%M")
    podstawa = f"{znacznik_czasu}_{_bezpieczna_nazwa_pliku(nazwa_modelu)}{sufiks_pliku}"
    sciezka_json = WYNIKI_DIR / f"{podstawa}.json"
    sciezka_md = WYNIKI_DIR / f"{podstawa}.md"

    sciezka_json.write_text(
        json.dumps({"model": nazwa_modelu, "metadane": metadane, "przypadki": wiersze}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linie_md = [
        f"# Ewaluacja agenta underwritera - model: {nazwa_modelu}",
        "",
        f"Data: {znacznik_czasu}",
        f"Liczba przypadkow: {metadane['liczba_przypadkow']}, w pelni zgodnych: {metadane['liczba_ok']}",
        f"Czas calkowity: {metadane['czas_calkowity_ms']:.0f} ms",
        f"Laczna liczba wywolan LLM: {metadane['wywolania_llm_laczne']}",
        f"Wariant grafu: {metadane.get('wariant', 'jeden')}, trasa zgodna: "
        f"{metadane.get('trasa_zgodna_laczne', '-')}/{metadane['liczba_przypadkow']}",
        f"Tokeny lacznie: wejscie {metadane['tokeny_we_laczne']}, wyjscie {metadane['tokeny_wy_laczne']}",
    ]
    if "ocr_stron_lacznie" in metadane:
        linie_md.append(
            f"OCR: {metadane['ocr_stron_lacznie']} stron, "
            f"{metadane['ocr_wywolania_sieciowe']} wywolan sieciowych, "
            f"{metadane['ocr_trafienia_cache']} trafien cache."
        )
        if "koszt_llm_usd_szacunkowy" in metadane:
            linie_md.append(
                f"Koszt LLM (szacunkowy, cennik do weryfikacji): "
                f"{metadane['koszt_llm_usd_szacunkowy']:.4f} USD"
            )
        if "vllm_metoda_structured_output" in metadane:
            # vLLM: brak cennika $/token (GPU wynajety rozlicza sie czasem najmu) -
            # patrz blok dla ModelVLLM w main() i SPEC_ETAP11.md.
            linie_md.append(
                f"vLLM metoda structured output: {metadane['vllm_metoda_structured_output']} "
                "(koszt USD nie liczony - rozliczenie GPU czasem najmu, nie tokenami)."
            )
    linie_md += [
        "",
        "```",
        _tabela_ascii(wiersze),
        "```",
        "",
        "## Pomylki",
    ]
    pomylki = [w for w in wiersze if not przypadek_w_pelni_zgodny(w)]
    if not pomylki:
        linie_md.append("Brak - wszystkie przypadki w pelni zgodne.")
    for w in pomylki:
        linie_md.append(
            f"- {w['id']}: decyzja oczekiwana={w['decyzja_llm_oczekiwana']}, "
            f"otrzymana={w['decyzja_llm_otrzymana']}; reguly oczekiwane={w['reguly_llm_oczekiwane']}, "
            f"otrzymane={w['reguly_llm_otrzymane']}; pola {w['pola_trafione']}/{w['pola_wszystkie']}; "
            f"silnik-na-polach-llm={w['decyzja_silnika_na_polach_llm_otrzymana']}"
            + (f"; BLAD: {w['blad']}" if w.get("blad") else "")
        )
    sciezka_md.write_text("\n".join(linie_md), encoding="utf-8")
    return sciezka_json, sciezka_md


def _main_szkody(args: argparse.Namespace, model: ModelAgenta, ids: list[str]) -> int:
    """Etap 10, `--modul szkody`: przypadki Z01..Z12. Z `--atrapa` zawsze BM25 lokalny
    (zero sieci); bez atrapy wyszukiwarka z env (WYSZUKIWARKA / AZURE_SEARCH_ENDPOINT)."""
    try:
        wyszukiwarka = WyszukiwarkaLokalna() if args.atrapa else zbuduj_wyszukiwarke()
    except BrakKonfiguracjiWyszukiwarki as e:
        print(f"BLAD: {e}", file=sys.stderr)
        return 2
    graf = wybierz_graf(
        args.wariant, model=model, checkpointer=InMemorySaver(),
        sciezka_wytycznych=WYTYCZNE_SCIEZKA, wyszukiwarka=wyszukiwarka,
    )

    wiersze: list[dict] = []
    przerwano_bezpiecznikiem = False
    start = time.monotonic()
    for id_przypadku in ids:
        stan = uruchom_szkode(graf, model, id_przypadku, zdjecia=args.zdjecia)
        if "RateLimit" in (stan.get("blad") or ""):
            print(f"BLAD: limit zapytan API w przypadku {id_przypadku} ({stan['blad']}). "
                  "Przerywam bez zapisu wynikow.", file=sys.stderr)
            return 4
        if "BrakKonfiguracjiAzure" in (stan.get("blad") or ""):
            # Przebieg 2026-10-21: bez AZURE_DOCINT_ENDPOINT wezel padal, 12/12 = blad_agenta i kod 0.
            print(f"BLAD: brak konfiguracji Azure w przypadku {id_przypadku} ({stan['blad']}). "
                  "Przerywam bez zapisu wynikow - sprawdz AZURE_OPENAI_ENDPOINT/AZURE_DOCINT_ENDPOINT.", file=sys.stderr)
            return 2
        if (stan.get("blad") or "").startswith("Blad wyszukiwania OWU"):
            print(f"BLAD: wyszukiwarka nie dziala w przypadku {id_przypadku} ({stan['blad']}). "
                  "Przerywam bez zapisu wynikow - to awaria konfiguracji, nie wynik modelu.", file=sys.stderr)
            return 5
        wiersz = porownaj_szkode(wczytaj_oczekiwany_szkody(id_przypadku), stan)
        wiersz.update(pola_wariantu(id_przypadku, stan))
        if args.zdjecia:
            # Etap 23: status sygnalu zdjecia z panelu (klucz tylko z flaga - bez niej wynik bez zmian).
            wiersz["zdjecie_status"] = podsumowanie_szkody(stan)["zdjecie"]["status"]
        wiersze.append(wiersz)
        if sum(w["wywolania_llm_razem"] for w in wiersze) > LIMIT_LACZNY_WYWOLAN:
            print(f"BLAD: bezpiecznik - przekroczono {LIMIT_LACZNY_WYWOLAN} wywolan LLM lacznie. Przerywam.",
                  file=sys.stderr)
            return 3
        tokeny_laczne = sum(w["_tokeny_we"] + w["_tokeny_wy"] for w in wiersze)
        if tokeny_laczne > args.limit_tokenow:
            print(f"BLAD: bezpiecznik kosztowy - {tokeny_laczne} tokenow > {args.limit_tokenow} "
                  f"po przypadku {id_przypadku}. Przerywam, zapisuje wyniki czesciowe.", file=sys.stderr)
            przerwano_bezpiecznikiem = True
            break

    tokeny_we = sum(w["_tokeny_we"] for w in wiersze)
    tokeny_wy = sum(w["_tokeny_wy"] for w in wiersze)
    metadane = {
        **_pola_metadanych_wariantu(args.wariant, model),
        "czas_calkowity_ms": (time.monotonic() - start) * 1000,
        **_metadane_licznikow(wiersze),
        "liczba_przypadkow": len(wiersze),
        "liczba_ok": sum(1 for w in wiersze if przypadek_szkody_zgodny(w)),
        "tokeny_we_laczne": tokeny_we,
        "tokeny_wy_laczne": tokeny_wy,
        "wyszukiwarka": wyszukiwarka.nazwa,
        "semantyczna": bool(getattr(wyszukiwarka, "semantyczna", False)),
        "wersja_owu": wersja_owu(),
    }
    if isinstance(model, ModelAzure):
        metadane["koszt_llm_usd_szacunkowy"] = (
            tokeny_we / 1_000_000 * CENA_GPT5_MINI_WE_USD_NA_MILION
            + tokeny_wy / 1_000_000 * CENA_GPT5_MINI_WY_USD_NA_MILION
        )
    metryki = metryki_szkod(metadane, wiersze)
    print(tabela_ascii_szkod(wiersze))
    print(f"\nWynik: {metadane['liczba_ok']}/{len(wiersze)} przypadkow w pelni zgodnych, "
          f"decyzje_ok={metryki['decyzje_ok']:.0f}, recall_wyszukiwania@5={metryki['recall_wyszukiwania_at_5']:.2f}.")
    print(f"Wariant: {args.wariant}, trasa zgodna: {metadane['trasa_zgodna_laczne']}/{len(wiersze)}, "
          f"wywolania LLM: {metadane['wywolania_llm_laczne']} (agenci {metadane['wywolania_llm_agenci_laczne']}"
          f" + supervisor {metadane['wywolania_supervisora_laczne']}), korekty supervisora: "
          f"{metadane['korekty_supervisora_laczne']}.")

    model_nazwa_bazowa = getattr(model, "nazwa_modelu", "nieznany")
    WYNIKI_DIR.mkdir(parents=True, exist_ok=True)
    podstawa = (f"{time.strftime('%Y%m%d-%H%M')}_szkody_{_bezpieczna_nazwa_pliku(model_nazwa_bazowa)}"
                f"{_sufiks_wariantu(args.wariant)}")
    sciezka_json = WYNIKI_DIR / f"{podstawa}.json"
    sciezka_md = WYNIKI_DIR / f"{podstawa}.md"
    sciezka_json.write_text(json.dumps({"model": model_nazwa_bazowa, "modul": "szkody", "metadane": metadane,
                                        "przypadki": wiersze}, ensure_ascii=False, indent=2), encoding="utf-8")
    sciezka_md.write_text(raport_md_szkod(model_nazwa_bazowa, wiersze, metadane), encoding="utf-8")
    print(f"Zapisano wyniki: {sciezka_json}")

    if args.mlflow:
        # Etap 14 (przeglad p. 8): do MLflow/Azure ML idzie JSON bez tekstow RAG (query/context/response/
        # ground_truth) - pelny JSON z tekstami zostaje lokalnie, czyta go sedzia (foundry_uruchom).
        sciezka_json_mlflow = WYNIKI_DIR / f"{podstawa}_mlflow.json"
        sciezka_json_mlflow.write_text(json.dumps(
            {"model": model_nazwa_bazowa, "modul": "szkody", "metadane": metadane,
             "przypadki": [{k: v for k, v in w.items() if k not in KLUCZE_RAG} for w in wiersze]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        parametry = {
            "dostawca": args.dostawca, "model": model_nazwa_bazowa, "przypadki": ids,
            "limit_tokenow": args.limit_tokenow, "atrapa": args.atrapa,
            "wyszukiwarka": metadane["wyszukiwarka"], "semantyczna": metadane["semantyczna"],
            "wersja_owu": metadane["wersja_owu"], "top_k": TOP_K, "wariant": args.wariant,
        }
        try:
            run_id = zaloguj_przebieg(
                parametry=parametry, metadane=metadane, wiersze=wiersze,
                artefakty=[sciezka_json_mlflow, sciezka_md], czesciowy=przerwano_bezpiecznikiem, zrodlo="uruchom",
                tagi_dodatkowe={"modul": "szkody", "klucz_przebiegu": podstawa}, wariant=args.wariant,  # Etap 14 m2: wiaze run z runem sedziego
                metryki=metryki, tabela=tabela_szkod_mlflow(wiersze),
            )
        except Exception as e:
            print(f"BLAD: MLflow: {e}", file=sys.stderr)
            return 5
        print(f"MLflow: zapisano run {run_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ewaluacja agenta underwritera na przypadkach demo.")
    parser.add_argument(
        "--przypadki", type=str, default=None,
        help="Lista id oddzielona przecinkami, np. W01,W05. Domyslnie wszystkie przypadki z dane/oczekiwane.",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Nazwa modelu Gemini (domyslnie zmienna GEMINI_MODEL albo gemini-3.8-flash).",
    )
    parser.add_argument(
        "--myslenie", type=str, default=None, choices=["low", "medium", "high"],
        help="thinking_level dla Gemini 3+ (domyslnie zmienna GEMINI_THINKING albo ustawienie modelu).",
    )
    parser.add_argument(
        "--limit-tokenow", type=int, default=LIMIT_TOKENOW_DOMYSLNY,
        help=f"Przerwij, gdy laczne tokeny przebiegu przekrocza limit (domyslnie {LIMIT_TOKENOW_DOMYSLNY}).",
    )
    parser.add_argument(
        "--atrapa", action="store_true",
        help="Uzyj atrapy modelu (dane z dane/oczekiwane) zamiast prawdziwego wywolania Gemini - bez sieci, bez klucza.",
    )
    parser.add_argument(
        "--dostawca", type=str, default="gemini", choices=["gemini", "azure", "vllm"],
        help="Dostawca LLM (domyslnie gemini). 'azure' = Azure OpenAI gpt-5-mini + OCR Document "
        "Intelligence. 'vllm' = model open-source serwowany przez vLLM (RunPod, API zgodne z "
        "OpenAI) + ten sam OCR Document Intelligence; konfiguracja wylacznie przez zmienne "
        "srodowiskowe VLLM_* (patrz agent/model_vllm.py, SPEC_ETAP11.md).",
    )
    parser.add_argument(
        "--reasoning", type=str, default=None, choices=["minimal", "low"],
        help="reasoning_effort dla Azure gpt-5-mini (domyslnie zmienna AZURE_OPENAI_REASONING albo 'low'). "
        "Ignorowane dla dostawcow gemini i vllm.",
    )
    parser.add_argument(
        "--mlflow", action="store_true",
        help="Po zapisaniu wynikow na dysk zaloguj przebieg do MLflow (Etap 8). Wymaga requirements-ewaluacja.txt.",
    )
    parser.add_argument(
        "--mlflow-trace", action="store_true",
        help="Jak --mlflow, dodatkowo wlacza mlflow.langchain.autolog() przed budowa grafu, "
        "zeby slady LangGraph/modelu byly powiazane z runem.",
    )
    parser.add_argument(
        "--zdjecia", action="store_true",
        help="Etap 23, tylko z --modul szkody: podaj dane/zdjecia_szkod/<ID>.jpg do grafu (wezel analizuj_zdjecie). "
        "Decyzje sie nie zmieniaja - zdjecie jest sygnalem dla likwidatora.",
    )
    parser.add_argument(
        "--wariant", type=str, default="jeden", choices=list(WARIANTY_GRAFU),
        help="Etap 24: orkiestracja grafu - 'jeden' (domyslny, dotychczasowy graf) albo 'wieloagentowy' "
        "(supervisor + agenci underwritingu, szkod i OWU). W wynikach: metadane.wariant, trasa, trasa_zgodna, "
        "liczniki supervisora; wywolania_llm_razem = agenci + supervisor.",
    )
    parser.add_argument(
        "--modul", type=str, default="wnioski", choices=["wnioski", "szkody"],
        help="Etap 10: 'szkody' = 12 zgloszen szkod z dane/szkody (RAG po OWU). Domyslnie 'wnioski'.",
    )
    args = parser.parse_args(argv)
    uzyj_mlflow = args.mlflow or args.mlflow_trace
    if args.modul == "szkody" and args.mlflow_trace:
        print("BLAD: --mlflow-trace dziala tylko dla --modul wnioski; dla szkod uzyj --mlflow.", file=sys.stderr)
        return 2

    if args.zdjecia and args.modul != "szkody":
        print("BLAD: --zdjecia dziala tylko z --modul szkody.", file=sys.stderr)
        return 2

    if args.przypadki:
        ids = [x.strip() for x in args.przypadki.split(",")]
    else:
        ids = wszystkie_id_szkod() if args.modul == "szkody" else _wszystkie_id_przypadkow()

    try:
        model = _zbuduj_model(args.atrapa, args.model, args.myslenie, args.dostawca, args.reasoning)
    except (BrakKluczaAPI, BrakKonfiguracjiAzure, BrakKonfiguracjiVLLM) as e:
        print(f"BLAD: {e}", file=sys.stderr)
        return 2

    resetuj_liczniki_ocr()
    if args.modul == "szkody":
        return _main_szkody(args, model, ids)

    # --mlflow-trace: run trzeba otworzyc PRZED budowa grafu - mlflow.langchain.autolog()
    # (domyslnie exclusive=False) wiaze slady z runem aktywnym w chwili WYWOLANIA modelu,
    # nie z runem otwartym pozniej przy logowaniu metryk.
    run_mlflow = None
    if args.mlflow_trace:
        try:
            import mlflow

            from ewaluacja.mlflow_log import ustaw_sledzenie

            # Azure ML nie ma API sladow (/api/2.0/mlflow/traces -> 404, sprawdzone 12.10.2026):
            # eksport sladow pada w tle, a przebieg konczy sie kodem 0 - cicha utrata sladow.
            if os.environ.get("MLFLOW_TRACKING_URI", "").startswith("azureml:"):
                print(
                    "BLAD: MLflow: Azure ML nie obsluguje sladow (traces). --mlflow-trace tylko z "
                    "backendem lokalnym (bez MLFLOW_TRACKING_URI); do Azure ML uzyj --mlflow.",
                    file=sys.stderr,
                )
                return 5
            ustaw_sledzenie()
            mlflow.langchain.autolog()
            run_mlflow = mlflow.start_run()
        except Exception as e:  # brak polaczenia z tracking URI, zly URI itp.
            print(f"BLAD: MLflow: {e}", file=sys.stderr)
            return 5

    checkpointer = InMemorySaver()
    graf = wybierz_graf(args.wariant, model=model, checkpointer=checkpointer, sciezka_wytycznych=WYTYCZNE_SCIEZKA)

    wiersze: list[dict] = []
    laczne_wywolania = 0
    przerwano_bezpiecznikiem = False
    start_calkowity = time.monotonic()

    for id_przypadku in ids:
        oczekiwany = _wczytaj_oczekiwany(id_przypadku)
        stan = _uruchom_przypadek(graf, model, id_przypadku)
        # Etap 24: suma agenci + supervisor (w `jeden` supervisor = 0, wartosc jak dotad).
        laczne_wywolania += stan.get("wywolania_llm", 0) + stan.get("wywolania_supervisora", 0)
        if laczne_wywolania > LIMIT_LACZNY_WYWOLAN:
            print(
                f"BLAD: bezpiecznik - przekroczono {LIMIT_LACZNY_WYWOLAN} wywolan LLM lacznie. Przerywam.",
                file=sys.stderr,
            )
            if run_mlflow is not None:
                mlflow.end_run(status="KILLED")  # przerwany - nieporownywalny z pelnym
            return 3
        if "BrakKonfiguracjiAzure" in (stan.get("blad") or ""):
            print(
                f"BLAD: brak konfiguracji Azure w przypadku {id_przypadku} ({stan['blad']}). "
                "Przerywam bez zapisu wynikow - sprawdz AZURE_OPENAI_ENDPOINT/AZURE_DOCINT_ENDPOINT.",
                file=sys.stderr,
            )
            if run_mlflow is not None:
                mlflow.end_run(status="KILLED")
            return 2
        if "RateLimit" in (stan.get("blad") or ""):
            # Limit dzienny nie minie w trakcie biegu - dalsze przypadki tylko
            # mnoza ponowienia i daja wynik mierzacy limit, nie jakosc modelu.
            print(
                f"BLAD: limit zapytan API w przypadku {id_przypadku} ({stan['blad']}). "
                "Przerywam bez zapisu wynikow.",
                file=sys.stderr,
            )
            if run_mlflow is not None:
                mlflow.end_run(status="KILLED")
            return 4
        wynik = porownaj_przypadek(oczekiwany, stan)
        wynik["_czas_ms"] = stan.get("_czas_ms", 0.0)
        wynik["_wywolania_llm"] = stan.get("wywolania_llm", 0)
        wynik["_tokeny_we"] = sum(w.get("tokeny_we") or 0 for w in stan.get("log", []))
        wynik["_tokeny_wy"] = sum(w.get("tokeny_wy") or 0 for w in stan.get("log", []))
        wynik.update(pola_wariantu(id_przypadku, stan))
        wiersze.append(wynik)
        tokeny_laczne = sum(w["_tokeny_we"] + w["_tokeny_wy"] for w in wiersze)
        if tokeny_laczne > args.limit_tokenow:
            print(
                f"BLAD: bezpiecznik kosztowy - {tokeny_laczne} tokenow > {args.limit_tokenow} "
                f"po przypadku {id_przypadku}. Przerywam, zapisuje wyniki czesciowe.",
                file=sys.stderr,
            )
            przerwano_bezpiecznikiem = True
            break

    czas_calkowity_ms = (time.monotonic() - start_calkowity) * 1000
    print(_tabela_ascii(wiersze))

    liczba_ok = sum(1 for w in wiersze if przypadek_w_pelni_zgodny(w))
    print(f"\nWynik: {liczba_ok}/{len(wiersze)} przypadkow w pelni zgodnych.")
    print(f"Laczny czas: {czas_calkowity_ms:.0f} ms, laczna liczba wywolan LLM: {laczne_wywolania}")
    print(f"Wariant: {args.wariant}, trasa zgodna: {sum(1 for w in wiersze if w['trasa_zgodna'])}/{len(wiersze)}.")

    model_nazwa_bazowa = getattr(model, "nazwa_modelu", "nieznany")
    nazwa_modelu = model_nazwa_bazowa
    if getattr(model, "myslenie", None):
        nazwa_modelu = f"{nazwa_modelu}_myslenie-{model.myslenie}"
    tokeny_we_laczne = sum(w["_tokeny_we"] for w in wiersze)
    tokeny_wy_laczne = sum(w["_tokeny_wy"] for w in wiersze)
    metadane = {
        **_pola_metadanych_wariantu(args.wariant, model),
        "czas_calkowity_ms": czas_calkowity_ms,
        **_metadane_licznikow(wiersze),
        "liczba_przypadkow": len(wiersze),
        "liczba_ok": liczba_ok,
        "tokeny_we_laczne": tokeny_we_laczne,
        "tokeny_wy_laczne": tokeny_wy_laczne,
    }
    if isinstance(model, ModelAzure) and not isinstance(model, ModelVLLM):
        # Cennik gpt-5-mini do weryfikacji (patrz stale CENA_GPT5_MINI_*_USD_NA_MILION).
        koszt_usd = (
            tokeny_we_laczne / 1_000_000 * CENA_GPT5_MINI_WE_USD_NA_MILION
            + tokeny_wy_laczne / 1_000_000 * CENA_GPT5_MINI_WY_USD_NA_MILION
        )
        oc = liczniki_ocr()
        metadane["ocr_stron_lacznie"] = oc["stron_ocr"]
        metadane["ocr_wywolania_sieciowe"] = oc["wywolania_sieciowe"]
        metadane["ocr_trafienia_cache"] = oc["trafienia_cache"]
        metadane["koszt_llm_usd_szacunkowy"] = koszt_usd
        print(
            f"OCR: {oc['stron_ocr']} stron (limit F0: 500/mies.), "
            f"{oc['wywolania_sieciowe']} wywolan sieciowych, {oc['trafienia_cache']} trafien cache."
        )
        print(f"Koszt LLM (szacunkowy, cennik do weryfikacji): {koszt_usd:.4f} USD")
    elif isinstance(model, ModelVLLM):
        # ModelVLLM dziedziczy po ModelAzure (ten sam OCR Document Intelligence) - stron/
        # wywolan OCR nadal warto zaraportowac. Koszt LLM NIE jest liczony wg cennika
        # gpt-5-mini: GPU wynajete na RunPod rozlicza sie czasem najmu, nie tokenami -
        # porownanie kosztu z gpt-5-mini wymaga osobnej stawki $/h (SPEC_ETAP11.md,
        # sekcja "otwarte"), nie ma jej w repo.
        oc = liczniki_ocr()
        metadane["ocr_stron_lacznie"] = oc["stron_ocr"]
        metadane["ocr_wywolania_sieciowe"] = oc["wywolania_sieciowe"]
        metadane["ocr_trafienia_cache"] = oc["trafienia_cache"]
        metadane["vllm_metoda_structured_output"] = getattr(model, "metoda_structured_output", None)
        metadane["vllm_max_tokens"] = getattr(model, "max_tokens", None)
        print(
            f"OCR: {oc['stron_ocr']} stron (limit F0: 500/mies.), "
            f"{oc['wywolania_sieciowe']} wywolan sieciowych, {oc['trafienia_cache']} trafien cache."
        )
        print(
            f"vLLM: model={model.nazwa_modelu}, metoda structured output="
            f"{metadane['vllm_metoda_structured_output']} "
            "(koszt USD nie liczony - GPU wynajety rozlicza sie czasem najmu, nie tokenami)."
        )
    sciezka_json, sciezka_md = _zapisz_wyniki(nazwa_modelu, wiersze, metadane, _sufiks_wariantu(args.wariant))
    print(f"Zapisano wyniki: {sciezka_json}")
    print(f"Zapisano wyniki: {sciezka_md}")

    if uzyj_mlflow:
        parametry = {
            "dostawca": args.dostawca,
            "model": model_nazwa_bazowa,
            "przypadki": ids,
            "limit_tokenow": args.limit_tokenow,
            "atrapa": args.atrapa,
            "wariant": args.wariant,
        }
        if args.dostawca == "azure":
            parametry["reasoning"] = getattr(model, "myslenie", None)
        elif args.dostawca == "vllm":
            # Nigdy base_url (identyfikuje pod RunPod) ani klucz - tylko dostawca,
            # nazwa modelu (juz w parametry["model"]) i metoda structured output.
            parametry["vllm_metoda_structured_output"] = getattr(model, "metoda_structured_output", None)
            parametry["vllm_max_tokens"] = getattr(model, "max_tokens", None)
        else:
            parametry["myslenie"] = getattr(model, "myslenie", None)
        try:
            run_id = zaloguj_przebieg(
                parametry=parametry,
                metadane=metadane,
                wiersze=wiersze,
                artefakty=[sciezka_json, sciezka_md],
                czesciowy=przerwano_bezpiecznikiem,
                zrodlo="uruchom",
                wariant=args.wariant,
            )
        except Exception as e:
            print(f"BLAD: MLflow: {e}", file=sys.stderr)
            return 5
        finally:
            if run_mlflow is not None:
                run_mlflow.__exit__(None, None, None)
        print(f"MLflow: zapisano run {run_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
