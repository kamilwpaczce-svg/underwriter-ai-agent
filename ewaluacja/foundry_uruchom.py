"""CLI ewaluacji szkod sedzia LLM w Azure AI Foundry (Etap 14, zadanie 5).

Spina czyste funkcje z `ewaluacja/foundry.py` z plikami wynikow, `azure.ai.evaluation.evaluate`
i (opcjonalnie) MLflow. Kody wyjscia (kazdy != 0 = przebieg nie liczy sie jako wynik):
0 OK, 2 brak konfiguracji, 3 plik wynikow sprzed Etapu 14, 4 wyjatek evaluate, 5 MLflow,
6 sedzia nie ocenil wiersza, 7 przebieg RAG niepelny, 8 projekt podany, ale brak studio_url.

RODO: na stdout/stderr tylko identyfikatory przypadkow, kody i liczby - nigdy tresci zapytan/odpowiedzi.
Modul nie importuje azure-ai-evaluation ani MLflow na poziomie modulu (CI/.venv ich nie ma)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ewaluacja import foundry

ROOT = Path(__file__).resolve().parent.parent
OCZEKIWANE_DOMYSLNE = ROOT / "dane" / "szkody" / "oczekiwane"
WORKERY_DOMYSLNIE = "3"  # PF_WORKER_COUNT; SDK domyslnie 10 - przy limicie TPM 50k gpt-5-mini daje 429 (DSZ0 pkt 5)


def uruchom_evaluate(**kwargs) -> dict:
    from azure.ai.evaluation import evaluate
    return evaluate(**kwargs)


def _ewaluatory(model_config: dict, rozumujacy: bool) -> dict:
    from azure.identity import DefaultAzureCredential
    return foundry.zbuduj_ewaluatory(model_config, DefaultAzureCredential(), rozumujacy)


def _zaloguj(**kwargs) -> str:
    from ewaluacja.mlflow_log import zaloguj_przebieg
    return zaloguj_przebieg(**kwargs)


def _blad(tekst: str, kod: int) -> int:
    print(f"BLAD: {tekst}", file=sys.stderr)
    return kod


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ewaluacja szkod sedzia LLM (azure-ai-evaluation) w Foundry.")
    p.add_argument("--wyniki", help="ewaluacja/wyniki/<klucz>.json z przebiegu szkod (wymagane takze z --mlflow-z).")
    p.add_argument("--projekt", help="URL projektu Foundry (domyslnie AZURE_AI_PROJECT_ENDPOINT).")
    p.add_argument("--bez-foundry", action="store_true", help="Bez logowania do portalu Foundry (tylko pliki lokalne).")
    p.add_argument("--sedzia", default=os.environ.get("AZURE_EVAL_DEPLOYMENT", "gpt-5-mini"),
                   help="Nazwa wdrozenia sedziego (domyslnie AZURE_EVAL_DEPLOYMENT albo gpt-5-mini).")
    p.add_argument("--bez-rozumowania", action="store_true", help="is_reasoning_model=False (sedzia bez rozumowania).")
    p.add_argument("--oczekiwane", default=str(OCZEKIWANE_DOMYSLNE), help="Katalog z oczekiwanymi wynikami szkod.")
    p.add_argument("--mlflow", action="store_true", help="Zaloguj ten przebieg takze do MLflow.")
    p.add_argument("--mlflow-z", help="Tylko logowanie do MLflow z gotowego <klucz>_sedzia.json (bez wywolan LLM).")
    return p


class BladWejscia(Exception):
    """Brak/uszkodzony plik wejsciowy (--wyniki, --oczekiwane, --mlflow-z) - kod 2, nie traceback."""


def _wczytaj_json(sciezka: Path) -> dict:
    try:
        dane = json.loads(sciezka.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # ValueError obejmuje JSONDecodeError i UnicodeDecodeError
        raise BladWejscia(f"nie mozna wczytac {sciezka}: {type(e).__name__}") from e
    if not isinstance(dane, dict):
        raise BladWejscia(f"{sciezka}: oczekiwany obiekt JSON.")
    return dane


def _wczytaj_wyniki(sciezka: Path) -> dict:
    dane = _wczytaj_json(sciezka)
    przypadki = dane.get("przypadki")
    if not isinstance(przypadki, list) or not all(isinstance(w, dict) for w in przypadki):
        raise BladWejscia(f"{sciezka}: brak listy 'przypadki' (to nie plik wynikow szkod).")
    return dane


def _oczekiwane_z_llm(katalog: Path) -> set[str]:
    """Przypadki, w ktorych graf MUSI dojsc do oceny LLM (decyzja_llm != null) - dzis 9 z 12."""
    if not katalog.is_dir():
        raise BladWejscia(f"brak katalogu oczekiwanych: {katalog} (--oczekiwane).")
    wynik = {p.stem for p in katalog.glob("*.json") if _wczytaj_json(p).get("decyzja_llm") is not None}
    if not wynik:  # zla sciezka dawalaby "0 oczekiwanych" = cichy sukces
        raise BladWejscia(f"brak oczekiwanych z decyzja_llm != null w {katalog} (--oczekiwane).")
    return wynik


def _bramka_pelnosci(wiersze: list[dict], katalog_oczekiwanych: Path) -> tuple[str, int] | None:
    """Wspolna dla main i --mlflow-z: kod 7, gdy przebieg RAG niepelny (graf padl / blad w wierszu /
    brak oceny LLM tam, gdzie oczekiwana jest decyzja LLM). Zwraca (komunikat, kod) albo None."""
    oczekiwane = _oczekiwane_z_llm(katalog_oczekiwanych)
    z_llm = {w["id"] for w in wiersze if w["ocenia_llm"]}
    bledy = [w["id"] for w in wiersze if w.get("blad")]
    if oczekiwane - z_llm or bledy:  # graf padl: 0 wierszy do sedziego != "wszystko OK"
        return (f"przebieg RAG niepelny: ocena LLM w {len(z_llm)}/{len(oczekiwane)} "
                f"(brak: {sorted(oczekiwane - z_llm)}), blad w {bledy}.", 7)
    return None


def _wiersze_bez_pol_rag(wiersze: list[dict]) -> list[str]:
    return [str(w.get("id")) for w in wiersze if any(k not in w for k in foundry.KLUCZE_JSONL)]


def _loguj_mlflow(klucz: str, dane: dict, tabela: list[dict], sedzia_czysty: dict, studio_url: str | None,
                  katalog: Path, parametry_sedziego: dict) -> int:
    """Run MLflow: metryki i tabela z `foundry`, artefakty = oczyszczony _sedzia.json + _rozjazdy.md
    (ustalenia sesji R1/R2: bez tresci, bez _sedzia.jsonl)."""
    # pelne sciezki (przeglad koncowy m1): komenda ma dzialac z dowolnego katalogu roboczego
    polecenie = (f"uruchom w .venv-ewaluacja: python -m ewaluacja.foundry_uruchom "
                 f'--mlflow-z "{katalog / f"{klucz}_sedzia.json"}" --wyniki "{katalog / f"{klucz}.json"}"')
    sedzia_mlflow = katalog / f"{klucz}_sedzia_mlflow.json"
    rozjazdy = katalog / f"{klucz}_rozjazdy.md"
    try:
        sedzia_mlflow.write_text(json.dumps(sedzia_czysty, ensure_ascii=False, indent=2), encoding="utf-8")
        rozjazdy.write_text(foundry.raport_rozjazdow_md(tabela, klucz, studio_url), encoding="utf-8")
        run_id = _zaloguj(
            parametry={"model": dane.get("model"), "klucz_przebiegu": klucz, **parametry_sedziego},
            metadane=dane.get("metadane") or {}, wiersze=[], artefakty=[sedzia_mlflow, rozjazdy], czesciowy=False,
            zrodlo="foundry",
            tagi_dodatkowe={"modul": "szkody-sedzia", "klucz_przebiegu": klucz, "foundry_url": studio_url or "-"},
            metryki=foundry.metryki_sedziego(tabela), tabela=foundry.tabela_mlflow(tabela),
        )
    except ImportError as e:  # MLflow tylko w .venv-ewaluacja
        return _blad(f"MLflow niedostepny w tym srodowisku ({type(e).__name__}); {polecenie}", 5)
    except Exception as e:
        return _blad(f"MLflow: {type(e).__name__}: {str(e)[:300]}; {polecenie}", 5)
    print(f"MLflow: zapisano run {run_id}")
    return 0


def _tylko_mlflow(sedzia_json: Path, wyniki: Path, katalog_oczekiwanych: Path) -> int:
    """Logowanie do MLflow z gotowego wyniku sedziego. Te same bramki co przebieg pelny: kod 2 dla plikow
    z roznych przebiegow, 3 stary plik, 7 przebieg niepelny, 6 wiersz z ocena LLM bez kompletu ocen -
    zawsze BEZ logowania (inaczej MLflow dostalby srednie z niepelnych/cudzych ocen)."""
    if sedzia_json.name != f"{wyniki.stem}_sedzia.json":
        return _blad(f"{sedzia_json.name} nie pasuje do {wyniki.name} (oczekiwano {wyniki.stem}_sedzia.json) "
                     "- pliki z roznych przebiegow.", 2)
    try:
        wynik = _wczytaj_json(sedzia_json)
        dane = _wczytaj_wyniki(wyniki)
        wiersze = dane["przypadki"]
        stare = _wiersze_bez_pol_rag(wiersze)
        if stare:
            return _blad(f"plik wynikow bez pol RAG (sprzed Etapu 14): {stare}.", 3)
        niepelny = _bramka_pelnosci(wiersze, katalog_oczekiwanych)
    except BladWejscia as e:
        return _blad(str(e), 2)
    if niepelny:
        return _blad(*niepelny)
    oceny = foundry.oceny_z_wyniku(wynik)
    brak = foundry.wiersze_bez_oceny(wiersze, oceny)
    if brak:
        return _blad(f"sedzia nie ocenil {brak} - MLflow NIE zalogowany; sprawdz {sedzia_json.name}.", 6)
    tabela = foundry.tabela_rozjazdow(wiersze, oceny)
    # sedzia/rozumowanie nieznane z pliku - nie zgadujemy w parametrach runu
    return _loguj_mlflow(wyniki.stem, dane, tabela, foundry.oczysc_sedzia_json(wynik), wynik.get("studio_url"),
                         wyniki.parent, {})


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.wyniki:
        return _blad("--wyniki wymagane (takze z --mlflow-z: tabela potrzebuje decyzja_ok).", 2)
    if args.mlflow_z:
        return _tylko_mlflow(Path(args.mlflow_z), Path(args.wyniki), Path(args.oczekiwane))
    sciezka = Path(args.wyniki)
    try:
        dane = _wczytaj_wyniki(sciezka)
    except BladWejscia as e:
        return _blad(str(e), 2)
    klucz, wiersze = sciezka.stem, dane["przypadki"]
    jsonl = sciezka.with_name(f"{klucz}_sedzia.jsonl")
    try:
        foundry.zapisz_jsonl(wiersze, jsonl)
    except foundry.BrakPolRag as e:
        return _blad(str(e), 3)
    try:
        niepelny = _bramka_pelnosci(wiersze, Path(args.oczekiwane))
    except BladWejscia as e:
        return _blad(str(e), 2)
    if niepelny:
        return _blad(*niepelny)
    endpoint = os.environ.get("AZURE_EVAL_ENDPOINT") or os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        return _blad("brak AZURE_EVAL_ENDPOINT/AZURE_OPENAI_ENDPOINT (sedzia).", 2)
    projekt = None if args.bez_foundry else (args.projekt or os.environ.get("AZURE_AI_PROJECT_ENDPOINT"))
    if not projekt and not args.bez_foundry:
        return _blad("brak projektu Foundry (--projekt / AZURE_AI_PROJECT_ENDPOINT); bez logowania: --bez-foundry.", 2)
    model_config = {"azure_endpoint": endpoint, "azure_deployment": args.sedzia,
                    "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")}
    os.environ.setdefault("PF_WORKER_COUNT", WORKERY_DOMYSLNIE)  # czytane przy tworzeniu klienta evaluate
    try:
        wynik = uruchom_evaluate(
            data=str(jsonl), evaluators=_ewaluatory(model_config, not args.bez_rozumowania),
            evaluator_config=foundry.mapowanie_kolumn(), evaluation_name=f"szkody-{klucz}",
            azure_ai_project=projekt,
            output_path=str(sciezka.with_name(f"{klucz}_sedzia.json")), tags={"klucz_przebiegu": klucz},
        )
    except Exception as e:  # blad SDK/uprawnien - nie wynik modelu; bez tresci wyjatku w calosci (RODO)
        return _blad(f"evaluate: {type(e).__name__}: {str(e)[:300]}", 4)
    oceny = foundry.oceny_z_wyniku(wynik)
    brak = foundry.wiersze_bez_oceny(wiersze, oceny)
    if brak:  # pusty wynik != wynik zerowy
        return _blad(f"sedzia nie ocenil {brak} - sprawdz _sedzia.json (kolumny *_reason/bledy).", 6)
    tabela = foundry.tabela_rozjazdow(wiersze, oceny)
    studio_url = wynik.get("studio_url")
    sciezka.with_name(f"{klucz}_rozjazdy.md").write_text(
        foundry.raport_rozjazdow_md(tabela, klucz, studio_url), encoding="utf-8")
    if projekt and not studio_url:  # raport juz zapisany - do diagnozy
        return _blad("projekt podany, ale evaluate nie zwrocil studio_url - przebieg NIE jest w Foundry.", 8)
    print(f"Foundry: {studio_url or 'pominieto (--bez-foundry)'}")
    if not args.mlflow:
        return 0
    return _loguj_mlflow(klucz, dane, tabela, foundry.oczysc_sedzia_json(wynik), studio_url, sciezka.parent,
                         {"sedzia": args.sedzia, "sedzia_rozumujacy": not args.bez_rozumowania})


if __name__ == "__main__":
    sys.exit(main())
