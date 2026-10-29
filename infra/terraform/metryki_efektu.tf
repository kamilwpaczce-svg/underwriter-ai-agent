// Etap 19c (zadanie 3) - workbook z pieciu metryk efektu rozwiazania + alert JAKOSCI (odsetek
// odejsc czlowieka od rekomendacji). Plik jest CALKOWICIE ADDYTYWNY: nic z main.tf / foundry.tf
// nie jest zmieniane. Z main.tf uzywa tylko: data.azurerm_resource_group.rg,
// data.azurerm_log_analytics_workspace.uw, azurerm_application_insights.uw oraz ISTNIEJACEJ
// action group azurerm_monitor_action_group.uw (Etap 13) - nowej nie tworzymy.
//
// Zrodlo prawdy dla zapytan: obserwowalnosc/metryki_efektu.kql (sekcje "// === N. ... ===").
// Sekcje 1-5 trafiaja do workbooka, sekcja 6 do alertu - Terraform czyta ten sam plik, wiec
// zapytania w repo, w workbooku i w alercie nie moga sie rozjechac. Parametr workbooka {Rola}
// (cloud_RoleName) zastepuje stala liste `dynamic(["uw-api", "uw-zasiew"])` z .kql; pozwala
// odfiltrowac ruch testowy (uw-test-alarmu nie ma na liscie domyslnej).

locals {
  kql_metryk = replace(file("${path.module}/../../obserwowalnosc/metryki_efektu.kql"), "\r\n", "\n")

  // split po "// === ": element 0 to naglowek pliku, 1-6 to sekcje "N. Tytul ===\n<zapytanie>".
  kql_sekcje = slice(split("// === ", local.kql_metryk), 1, 7)

  kql_role_stale = "dynamic([\"uw-api\", \"uw-zasiew\"])"

  // Tytul = pierwszy wiersz sekcji bez koncowego " ===" i numeru; zapytanie = reszta.
  tytuly_metryk = [
    for s in slice(local.kql_sekcje, 0, 5) :
    trimsuffix(split("\n", s)[0], " ===")
  ]

  zapytania_metryk = [
    for s in slice(local.kql_sekcje, 0, 5) :
    replace(
      join("\n", slice(split("\n", s), 1, length(split("\n", s)))),
      local.kql_role_stale,
      "dynamic([{Rola}])"
    )
  ]

  // Zapytanie alertu (sekcja 6): wiersz TYLKO gdy warunek spelniony (filtr `where` po summarize).
  zapytanie_alertu_odejsc = join("\n", slice(split("\n", local.kql_sekcje[5]), 1, length(split("\n", local.kql_sekcje[5]))))
}

resource "azurerm_application_insights_workbook" "metryki_efektu" {
  // Nazwa workbooka MUSI byc GUID-em; uuidv5 daje stala, powtarzalna wartosc (bez zmian miedzy planami).
  name                = uuidv5("dns", "uw-demo-metryki-efektu")
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  display_name        = "uw: metryki efektu rozwiazania (19c)"
  source_id           = lower(azurerm_application_insights.uw.id)

  data_json = templatefile("${path.module}/metryki_efektu_workbook.json.tftpl", {
    workspace_id = data.azurerm_log_analytics_workspace.uw.id
    tytuly       = local.tytuly_metryk
    zapytania    = local.zapytania_metryk
  })
}

// Alert JAKOSCI, nie awarii (awarie lapie uw-demo-alert-awaria z main.tf). Model dziala technicznie,
// ale ludzie przestaja mu ufac: > 50% decyzji czlowieka odbiega od rekomendacji w 24 h, min. 5 decyzji.
//
// Lekcja z Etapu 13: Count po `summarize` zawsze daje wiersz (0 tez jest wierszem), wiec alert
// strzelalby stale. Zapytanie z sekcji 6 .kql ma `| where decyzje >= min_decyzji and
// odsetek_odejsc_pct > prog_odejsc_pct` PO summarize - zwraca 0 wierszy w stanie zdrowym i 1 w chorym.
// Regula liczy wiersze: Count > 0.
//
// Okno P1D = okno zapytania (ago(24h)). Czestotliwosc PT1H: alert jakosci nie musi reagowac w
// minuty, a kazda ewaluacja kosztuje. Progi (50%, 5, 24 h) sa WSTEPNE - przed wdrozeniem przejsc
// skill nadzor-automatu. Role uw-api i uw-zasiew: zasiew 19c musi moc odpalic alert w tescie.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "odejscia" {
  name                = "uw-demo-alert-odejscia"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location

  evaluation_frequency    = "PT1H"
  window_duration         = "P1D"
  scopes                  = [data.azurerm_log_analytics_workspace.uw.id]
  severity                = 3
  auto_mitigation_enabled = true

  display_name = "uw: > 50% decyzji czlowieka odbiega od rekomendacji agenta"
  description  = <<-OPIS
    Co padlo: w ostatnich 24 h co najmniej 5 decyzji czlowieka (span wniosek.wznow z atrybutem
    uw.odejscie_od_rekomendacji) i wiecej niz 50% z nich odbiega od rekomendacji agenta. To alert
    JAKOSCI, nie awarii: agent dziala technicznie, ale ludzie przestali mu ufac (dryf).
    Skutek: rekomendacje agenta sa mniej wiarygodne niz zakladano; wnioski nadal wymagaja decyzji
    czlowieka, wiec nic nie jest wydawane automatycznie.
    Kroki: 1) workbook "uw: metryki efektu rozwiazania (19c)" - kafelek odsetka odejsc;
    2) GET /wnioski/{id}/audyt dla odbiegajacych wnioskow (pole odejscie_od_rekomendacji, komentarz
    czlowieka) - czy to jeden typ dokumentu / jedna regula; 3) czy zmienil sie model, wytyczne albo
    rozklad wnioskow (nowy broker); 4) rozwazyc ewaluacje 19a na swiezych przypadkach.
    Czego NIE robic: nie podnosic progu 50% ani minimum 5 decyzji, zeby alert zniknal, bez decyzji.
    Test alertu: obserwowalnosc/zasiej_wnioski.py --stan chory (rola uw-zasiew).
  OPIS

  criteria {
    query = local.zapytanie_alertu_odejsc

    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"
  }

  action {
    action_groups = [azurerm_monitor_action_group.uw.id]
  }
}
