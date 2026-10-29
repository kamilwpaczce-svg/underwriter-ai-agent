# AI Act - klasyfikacja i mapowanie wymagan

> Nie jest to porada prawna. Stan prawny na 11.10.2026, po Rozporzadzeniu (UE) 2026/1744
> ("Digital Omnibus on AI", Dz.U. UE z 24.07.2026, obowiazuje od 27.07.2026):
> https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng

## 1. Klasyfikacja systemu

**Czym jest system:** asystent underwritera w ubezpieczeniu **mienia firm**. Czyta wniosek
(PDF/skan), wyciaga pola, sprawdza je z wytycznymi (R01-R09) i proponuje decyzje. Decyzje
koncowa zawsze podejmuje czlowiek.

**Wysokie ryzyko?** Nie. Zalacznik III pkt 5(c) obejmuje systemy AI "intended to be used for
risk assessment and pricing in relation to natural persons in the case of life and health
insurance". Ubezpieczenie mienia osob prawnych nie jest ani na zyciu, ani zdrowotne, ani nie
dotyczy osob fizycznych. Nie stosuje sie wiec rozdzial III sekcja 2 (art. 8-15) ani obowiazki
podmiotu stosujacego z art. 26.

**Dlaczego mimo to mapujemy art. 9-15:** z trzech powodow.

- Ten sam wzorzec (ekstrakcja z wniosku, potem rekomendacja) przeniesiony na ubezpieczenia na
  zycie lub zdrowotne osob fizycznych staje sie systemem wysokiego ryzyka.
- Ubezpieczyciele zwykle wymagaja tych samych kontroli wewnetrznie, niezaleznie od
  klasyfikacji (nadzor, audyt, DORA).
- Taniej jest zaprojektowac je od poczatku niz doklejac pozniej.

Ponizsze mapowanie jest dobrowolne.

## 2. Kalendarz (po Omnibusie)

| Data | Co zaczyna obowiazywac |
|---|---|
| 1.08.2024 | wejscie w zycie AI Act |
| 2.02.2025 | zakazane praktyki (art. 5), art. 4 |
| 2.08.2025 | obowiazki dostawcow modeli GPAI |
| 2.08.2026 | art. 50 (przejrzystosc); znakowanie tresci syntetycznych z okresem przejsciowym do 2.12.2026 |
| 2.12.2027 | systemy wysokiego ryzyka z Zalacznika III (m.in. 5(c)) |
| 2.08.2028 | systemy wysokiego ryzyka z Zalacznika I (produkty regulowane) |

Art. 4 (AI literacy) po Omnibusie: obowiazek "support the development of AI literacy"
zamiast twardego zapewnienia wystarczajacego poziomu kompetencji.

## 3. Mapowanie art. 9-15 na kod

| Artykul | Wymaganie (skrot) | Jak to robi demo | Gdzie |
|---|---|---|---|
| 9 - zarzadzanie ryzykiem | identyfikacja i ograniczanie ryzyk | Trzy zidentyfikowane ryzyka i ich kontrole: (1) halucynacja ekstrakcji, ograniczana walidacja pol i niezaleznym silnikiem regul; (2) wstrzykniecie polecen w dokumencie, ograniczane flaga `podejrzane_instrukcje` i zakazem ich wykonywania; (3) bledna regula, ograniczana porownaniem LLM z silnikiem i flaga rozbieznosci | `agent/instrukcje.py:54`, `agent/schematy.py:65`, `wytyczne/wytyczne_mienie_v1.yaml` |
| 10 - dane | jakosc i reprezentatywnosc danych | Wylacznie dane syntetyczne (generator, NIP z poprawna suma kontrolna), zero danych osobowych. Wzorzec oczekiwanych wynikow tez bywa bledny: W10 i W12 wykryte w ewaluacji i poprawione | `generator/`, `dane/oczekiwane/` |
| 11 - dokumentacja techniczna | opis systemu i decyzji projektowych | Specyfikacja kazdego etapu i ten dokument | `SPEC_ETAP1.md`-`SPEC_ETAP6.md`, `docs/` |
| 12 - rejestrowanie zdarzen | automatyczne logi przez caly cykl zycia | Tabela audytu: przyjecie wniosku, rekomendacja agenta albo blad, decyzja czlowieka z flaga odejscia od rekomendacji. Kod aplikacji wykonuje tylko INSERT. **Brak:** wymuszenia na poziomie bazy (trigger albo REVOKE UPDATE/DELETE) | `api/baza.py:55`, `api/baza.py:91`, `api/trasy.py:209` |
| 13 - przejrzystosc wobec uzytkownika | uzytkownik rozumie wynik i jego ograniczenia | Baner "rekomendacja wygenerowana przez AI", uzasadnienie z identyfikatorami regul, decyzja LLM obok decyzji deterministycznego silnika | `frontend/components/SekcjaAnaliz.tsx` (`baner-ai`) |
| 14 - nadzor czlowieka | czlowiek moze zrozumiec, zignorowac, nadpisac; ochrona przed automation bias (14(4)(b)) | Graf zatrzymuje sie przed decyzja (`interrupt`). Czlowiek moze wybrac dowolna decyzje. Odejscie od rekomendacji LLM lub silnika wymaga komentarza (API zwraca 422) i jest zapisywane w audycie. Rozbieznosc LLM i silnika jest flagowana | `agent/wezly.py:194`, `api/trasy.py:177` |
| 15 - dokladnosc, odpornosc, cyberbezpieczenstwo | zmierzona dokladnosc, odpornosc na manipulacje | Ewaluacja na 14 przypadkach z raportem pola po polu. Test wstrzykniecia (W13). Limit 6 wywolan LLM na wniosek. W Azure: Entra (Easy Auth), Managed Identity do OpenAI i Document Intelligence, OIDC w CI bez sekretow, API bez publicznego ingresu | `ewaluacja/`, `tests/test_dane.py:221`, `agent/wezly.py:22`, `frontend/app/api/[...sciezka]/route.ts:41` |

**Stabilnosc wyniku (art. 15):** ten sam zestaw i model Gemini dal 13/14 w pelni zgodnych
na prompcie z Etapu 2 i 11/14 po poprawkach promptu z Etapu 5, przy decyzjach poprawnych
14/14 w obu przebiegach. Z pojedynczych przebiegow nie da sie oddzielic wplywu zmiany promptu
od niedeterminizmu modelu. Produkcyjnie: kilka przebiegow na kazda zmiane promptu lub modelu
i sledzenie rozkladu, nie jednej liczby.

## 4. Pozostale przepisy

- **Art. 50 (przejrzystosc):** system nie rozmawia z osobami fizycznymi i nie generuje tresci
  publikowanych na zewnatrz. Uzytkownik wewnetrzny i tak widzi baner AI.
- **Art. 4 (AI literacy):** po stronie organizacji wdrazajacej, czyli szkolenie underwriterow
  z ograniczen systemu. Poza zakresem kodu.
- **GPAI (rozdzial V):** obowiazki ciaza na dostawcach modeli (OpenAI/Microsoft, Google), nie
  na integratorze.
- **RODO art. 22:** decyzja nie jest podejmowana wylacznie automatycznie, bo zatwierdza ja
  czlowiek z mozliwoscia nadpisania. Dane w demo sa syntetyczne.

## 5. Zastrzezenia wdrozenia demo

- **Lokalizacja przetwarzania:** wdrozenie `gpt-5-mini` w Azure OpenAI dziala w trybie
  **GlobalStandard**, wiec inferencja moze odbywac sie poza UE. Produkcyjnie: DataZone EU albo
  wdrozenie regionalne. Document Intelligence i dane (Postgres) sa w regionach UE.
- **Model ewaluowany a model wdrozony:** ewaluacja zostala wykonana na Gemini i na Azure
  OpenAI. Wyniki nie przenosza sie automatycznie miedzy modelami ani wersjami.

## 6. Czego brakuje do produkcji

1. Audyt append-only wymuszony w bazie (trigger albo uprawnienia), nie tylko w kodzie.
2. Zdefiniowana retencja logow. Dla systemu wysokiego ryzyka art. 26 ust. 6 wymaga
   co najmniej 6 miesiecy.
3. Monitoring dryfu: okresowa ewaluacja na probce realnych wnioskow i alert na spadek
   zgodnosci.
4. DPIA (RODO art. 35), gdy w gre wchodza dane osobowe.
5. Jesli system zostanie rozszerzony na zycie lub zdrowie osob fizycznych:
   - system zarzadzania jakoscia (art. 17);
   - rejestracja w bazie UE (art. 49);
   - monitorowanie po wprowadzeniu do obrotu (art. 72);
   - zglaszanie powaznych incydentow (art. 73).

## 7. Ocena szkod (Etap 10)

- **Zakres:** asystent likwidatora szkod w ubezpieczeniu mienia firm. System proponuje decyzje
  o pokryciu (`POKRYTA`/`ODMOWA`/`UZUPELNIENIE`/`SKIEROWANIE`) z cytatem z OWU. Decyzje koncowa
  zawsze zatwierdza czlowiek (`interrupt` w grafie, ta sama sciezka zatwierdzenia i audytu co
  dla wnioskow); odejscie od decyzji po regulach wymaga komentarza.
- **Klasyfikacja:** bez zmian wzgledem sekcji 1 - ubezpieczenie mienia, nie zycia ani zdrowia
  osob fizycznych, wiec Zalacznik III pkt 5(c) nie ma zastosowania.
- **Przejrzystosc i nadzor (art. 13-14, stosowane dobrowolnie jak w sekcji 3):** UI pokazuje
  pelna tresc cytowanych ustepow OWU, wynik sprawdzenia polisy (S01-S04) i wynik kontroli
  cytatow. Cytat spoza fragmentow podanych modelowi albo decyzja bez cytatu -> automatycznie
  `SKIEROWANIE`.
- **Dokladnosc (art. 15):** ewaluacja na 12 fikcyjnych zgloszeniach (`dane/szkody/`), osobno
  trafnosc decyzji, trafnosc cytatu i recall samego wyszukiwania; przebiegi w MLflow z tagiem
  `modul=szkody`.
- **Dane:** zgloszenia, polisy i OWU sa fikcyjne. Indeks Azure AI Search jest w regionie UE
  (polandcentral); embeddingi `text-embedding-3-small` w trybie GlobalStandard - inferencja moze
  odbywac sie poza UE (jak w sekcji 5).

### Zdjecie szkody (Etap 23)

- **Sygnal pomocniczy, nie decyzja:** analiza zdjecia (gpt-5-mini, ocena "na slepo" bez zgloszonej przyczyny,
  zgodnosc ze zgloszeniem liczona kodem w `agent/zdjecia.py`) daje likwidatorowi wiersz w panelu: zgodnosc
  `ZGODNE` / `NIEZGODNE` / `NIEUSTALONA` i sygnal dlugotrwalosci. Decyzje (`POKRYTA`/`ODMOWA`/`UZUPELNIENIE`/
  `SKIEROWANIE`) podejmuje czlowiek, jak w pozostalej czesci sekcji; sygnal ze zdjecia nie zmienia ani decyzji
  po regulach, ani kodow S01-S04, ani kontroli cytatow, ani trasy w grafie.
- **Dowod w kodzie:** `test_decyzja_i_trasa_identyczne_ze_zdjeciem_i_bez` (`tests/test_graf_szkody.py`) dla Z01-Z12
  bez zdjecia, ze zdjeciem wlasnym i ze zdjeciem z pary niezgodnej N1-N6 wymaga identycznej decyzji w panelu i
  identycznej trasy (poza samym wezlem `analizuj_zdjecie`). Bieg na zywo: 12/12 decyzji jak w Etapie 19a
  (`docs/ROZWOJ.md`, Etap 23).
- **Dokladnosc (art. 15) i jej granica:** na 18 pozycjach z generowanymi zdjeciami model trafia rodzaj szkody w
  9-11 z 12 przypadkow, wykrywa 3-4 z 5 niezgodnych par (para N6 nigdy), a 1-3 z 12 zgodnych zdjec oznacza
  falszywym alarmem (zakresy z 5 biegow). Zdjecia pochodza z generatora i sa czytelniejsze niz zdjecia od
  klientow, wiec wynik nie przenosi sie na produkcje (README, "Zdjecie szkody"). Pewnosc modelu nie jest
  skalibrowana. Wlasnie dlatego sygnal jest tylko podpowiedzia dla czlowieka.
