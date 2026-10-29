using 'main.bicep'

// Haslo NIE jest tu zapisane literalnie - czytane w czasie wdrazania ze zmiennej
// srodowiskowej procesu PowerShell (patrz infra/README.md, krok b - generowanie
// hasla i zapisanie go WYLACZNIE do zmiennej srodowiskowej, nigdy do pliku/repo).
param hasloPostgres = readEnvironmentVariable('HASLO_POSTGRES_ETAP6')

// swedencentral: RegionalAllocationFailed dla B1ms (2026-10-11). Gdy i tu zabraknie
// mocy, sprobuj 'northeurope'. Zmiana regionu istniejacego serwera = usuniecie i nowy.
param lokalizacjaPostgres = 'polandcentral'

// Pozostale parametry maja sensowne wartosci domyslne w main.bicep (nazwy zasobow
// z SPEC_ETAP6.md, obraz zastepczy, brak reguly firewalla admina) - nie trzeba ich
// tu nadpisywac przy pierwszym wdrozeniu. Przy KOLEJNYM `deployment group create`
// PRZEKAZ biezace obrazy (obrazApi/obrazWeb), inaczej ten plik cofnie Container Apps
// do obrazu zastepczego - patrz komenda PowerShell w infra/README.md.

// Etap 13 - connection string Application Insights (infra/terraform output
// `connection_string`, po `terraform apply` - infra/terraform/README.md, sekcja
// "Polaczenie z Bicepem"). WYMAGANY - jak przy hasloPostgres, brak tej zmiennej
// srodowiskowej ma wywrocic ten build GLOSNO (readEnvironmentVariable bez defaultu
// rzuca blad), a nie po cichu skasowac sekret i zmienne OTEL w uw-api. Nigdy nie
// zapisywac tu literalnie, tylko ze zmiennej srodowiskowej.
param appInsightsConnectionString = readEnvironmentVariable('APPINSIGHTS_CONNECTION_STRING_ETAP13')
