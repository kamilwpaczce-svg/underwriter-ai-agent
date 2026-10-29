// Etap 6 - wdrozenie na Azure Container Apps z Managed Identity.
// Zero sekretow dostepu do uslug Azure - jedyny sekret to haslo Postgresa
// (parametr @secure(), ladowany do sekretu Container Apps). Reszta uwierzytelnienia
// (ACR, Blob Storage, Azure OpenAI, Document Intelligence) idzie przez
// User-assigned Managed Identity `uw-demo-id` (role RBAC ponizej).
//
// Zasoby istniejace z Etapu 5 (Azure OpenAI, Document Intelligence) sa dolaczane
// przez `existing` - ten plik ich NIE tworzy ani nie zmienia.
//
// Deploy w tej samej grupie zasobow co zasoby istniejace (rg-underwriter-demo).
targetScope = 'resourceGroup'

@description('Haslo administratora Postgresa. Generowane w PowerShellu (infra/README.md), nigdy nie trafia do repo ani do outputow tego pliku.')
@secure()
param hasloPostgres string

@description('Login administratora Postgresa (nie sekret - sama nazwa).')
param administratorLoginPostgres string = 'underwriter'

@description('Nazwa bazy danych aplikacji w Postgresie.')
param nazwaBazyDanych string = 'underwriter'

@description('Obraz kontenera API. Domyslnie publiczna zaslepka - pierwsze wdrozenie, zanim CI/CD wypchnie prawdziwy obraz z ACR. Przy ponownym `deployment group create` PRZEKAZ BIEZACY obraz (patrz infra/README.md), inaczej Bicep cofnie Container App do tej zaslepki.')
param obrazApi string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Obraz kontenera frontendu. To samo zastrzezenie co przy `obrazApi`.')
param obrazWeb string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Publiczny adres IP administratora do opcjonalnej reguly firewalla Postgresa (dostep z wlasnego komputera do psql/narzedzi). Puste = brak reguly.')
param adresIpAdmina string = ''

@description('Region zasobow - musi byc zgodny z istniejacymi zasobami Etapu 5.')
param lokalizacja string = resourceGroup().location

@description('Region Postgresa - osobny, bo 2026-10-11 swedencentral zwrocil RegionalAllocationFailed dla B1ms (brak mocy na koncie trial). Opoznienie miedzyregionowe ~20 ms, bez znaczenia dla demo.')
param lokalizacjaPostgres string = lokalizacja

@description('Nazwa istniejacego zasobu Azure OpenAI (Etap 5).')
param nazwaAzureOpenAi string = 'uw-demo-aoai-xx1'

@description('Nazwa wdrozenia modelu w Azure OpenAI.')
param azureOpenAiDeployment string = 'gpt-5-mini'

@description('Wersja API Azure OpenAI.')
param azureOpenAiApiVersion string = '2025-04-01-preview'

@description('Poziom wnioskowania (reasoning) modelu Azure OpenAI.')
param azureOpenAiReasoning string = 'low'

@description('Endpoint istniejacej uslugi Azure AI Search (Etap 10). Usluga celowo poza Bicepem - trafi do Terraform.')
param azureSearchEndpoint string = 'https://uw-demo-search-xx1.search.windows.net'

@description('Nazwa indeksu OWU w Azure AI Search (rag/indeksuj_owu.py).')
param azureSearchIndex string = 'owu-mienie-v1'

@description('Nazwa wdrozenia embeddingow w Azure OpenAI.')
param azureOpenAiEmbeddingDeployment string = 'text-embedding-3-small'

@description('Semantic ranker AI Search: 1 = wlaczony (konfiguracja owu-semantyczna), 0 = wylaczony.')
@allowed([
  '0'
  '1'
])
param azureSearchSemantic string = '0'

@description('Nazwa istniejacego zasobu Document Intelligence (Etap 5).')
param nazwaDocumentIntelligence string = 'uw-demo-docint-xx1'

@description('Nazwa kontenera blob na wnioski.')
param kontenerBlob string = 'wnioski'

@description('Connection string Application Insights (Etap 13, infra/terraform output `connection_string` - patrz infra/terraform/README.md, krok "Polaczenie z Bicepem"). WYMAGANY, bez wartosci domyslnej - jak hasloPostgres, brak zmiennej srodowiskowej ma wywrocic ten build GLOSNO, a nie po cichu skasowac sekret i zmienne OTEL w uw-api przy ponownym `deployment group create`. Zasoby monitoringu powstaja w Terraform PRZED pierwszym uruchomieniem tego Bicepu z prawdziwa wartoscia (patrz README) - przy najzupelniej pierwszym wdrozeniu (przed `terraform apply`) nie da sie jeszcze przekazac wartosci sensownej, patrz README.')
@secure()
param appInsightsConnectionString string

var nazwaLogAnalytics = 'uw-demo-logs'
var nazwaSrodowiska = 'uw-demo-env'
var nazwaAcr = 'uwdemoacrxx1'
var nazwaPostgres = 'uw-demo-pg-xx2' // xx1 zablokowana: duch nieudanego wdrozenia w swedencentral (2026-10-11)
var nazwaStorage = 'uwdemostxx1'
var nazwaTozsamosci = 'uw-demo-id'
var nazwaApi = 'uw-api'
var nazwaWeb = 'uw-web'

// Wbudowane role RBAC (ID stale dla calego Azure, nie zalezne od subskrypcji).
var rolaAcrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var rolaCognitiveServicesOpenAiUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var rolaCognitiveServicesUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
var rolaStorageBlobDataContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

// ---------------------------------------------------------------------------
// Tozsamosc uzywana przez obie Container Apps (rejestr, blob, Azure OpenAI, DocInt).
// ---------------------------------------------------------------------------
resource tozsamosc 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: nazwaTozsamosci
  location: lokalizacja
}

// ---------------------------------------------------------------------------
// Log Analytics + Container Apps Environment.
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: nazwaLogAnalytics
  location: lokalizacja
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource srodowisko 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: nazwaSrodowiska
  location: lokalizacja
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Container Registry - admin user wylaczony, dostep wylacznie przez tozsamosc.
// ---------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: nazwaAcr
  location: lokalizacja
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource przypisanieAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, tozsamosc.id, rolaAcrPull)
  scope: acr
  properties: {
    principalId: tozsamosc.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: rolaAcrPull
  }
}

// ---------------------------------------------------------------------------
// Storage Account - bez kluczy dostepowych (allowSharedKeyAccess=false),
// kontener prywatny, dostep wylacznie przez Managed Identity (Storage Blob Data Contributor).
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: nazwaStorage
  location: lokalizacja
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource kontener 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: kontenerBlob
  properties: {
    publicAccess: 'None'
  }
}

resource przypisanieBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, tozsamosc.id, rolaStorageBlobDataContributor)
  scope: storage
  properties: {
    principalId: tozsamosc.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: rolaStorageBlobDataContributor
  }
}

// ---------------------------------------------------------------------------
// Postgres Flexible Server - jedyny sekret aplikacji (haslo).
// Swiadomy kompromis demo: publiczny endpoint + "Allow public access from any
// Azure service" (reguła 0.0.0.0-0.0.0.0), bo Container Apps Consumption nie ma
// stalych adresow wychodzacych (brak mozliwosci zawezenia firewalla do konkretnych
// IP). Produkcyjnie: VNet-integrated environment + private endpoint Postgresa.
// Uwierzytelnienie haslem (nie Entra) - tez kompromis opisany w infra/README.md.
// ---------------------------------------------------------------------------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: nazwaPostgres
  location: lokalizacjaPostgres
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '17'
    administratorLogin: administratorLoginPostgres
    administratorLoginPassword: hasloPostgres
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource bazaDanych 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: nazwaBazyDanych
}

resource regulaFirewallaAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource regulaFirewallaAdmina 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!empty(adresIpAdmina)) {
  parent: postgres
  name: 'AdminDemo'
  properties: {
    startIpAddress: adresIpAdmina
    endIpAddress: adresIpAdmina
  }
}

// ---------------------------------------------------------------------------
// Zasoby istniejace z Etapu 5 - TYLKO odczyt (endpoint) i nadanie roli tozsamosci.
// ---------------------------------------------------------------------------
resource azureOpenAi 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: nazwaAzureOpenAi
}

resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: nazwaDocumentIntelligence
}

resource przypisanieOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(azureOpenAi.id, tozsamosc.id, rolaCognitiveServicesOpenAiUser)
  scope: azureOpenAi
  properties: {
    principalId: tozsamosc.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: rolaCognitiveServicesOpenAiUser
  }
}

resource przypisanieDocIntUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(documentIntelligence.id, tozsamosc.id, rolaCognitiveServicesUser)
  scope: documentIntelligence
  properties: {
    principalId: tozsamosc.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: rolaCognitiveServicesUser
  }
}

// ---------------------------------------------------------------------------
// Container App API - ingress WEWNETRZNY (bez adresu w internecie).
// Max 1 replika celowo: agent biegnie w tle w procesie API, migracje Alembic
// odpalaja sie przy starcie (MIGRACJE_PRZY_STARCIE=1) - dwie repliki = wyscig
// migracji. Swiadomy kompromis demo, opisany w infra/README.md.
// ---------------------------------------------------------------------------
resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: nazwaApi
  location: lokalizacja
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${tozsamosc.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: srodowisko.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: tozsamosc.id
        }
      ]
      secrets: [
        {
          // Jedyny sekret aplikacji - haslo Postgresa, zlozone tu w pelny DATABASE_URL.
          // Nigdy nie trafia do outputow ani logow Bicepa.
          name: 'database-url'
          value: 'postgresql://${administratorLoginPostgres}:${hasloPostgres}@${postgres.properties.fullyQualifiedDomainName}:5432/${nazwaBazyDanych}?sslmode=require'
        }
        {
          // Etap 13 - appInsightsConnectionString jest WYMAGANY (bez wartosci domyslnej),
          // wiec ten sekret zawsze istnieje - patrz opis parametru.
          name: 'appinsights-cs'
          value: appInsightsConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'uw-api'
          image: obrazApi
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'MODEL_AGENTA', value: 'azure' }
            { name: 'AZURE_CLIENT_ID', value: tozsamosc.properties.clientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAi.properties.endpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: azureOpenAiDeployment }
            { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAiApiVersion }
            { name: 'AZURE_OPENAI_REASONING', value: azureOpenAiReasoning }
            { name: 'AZURE_DOCINT_ENDPOINT', value: documentIntelligence.properties.endpoint }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'KONTENER_BLOB', value: kontenerBlob }
            { name: 'MIGRACJE_PRZY_STARCIE', value: '1' }
            // Etap 10 - modul szkodowy (RAG). Dostep do Search przez RBAC (uw-demo-id ma
            // Search Index Data Reader), bez kluczy. WYSZUKIWARKA=azure: bledna konfiguracja
            // wywraca start API zamiast cichego powrotu do BM25.
            { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
            { name: 'AZURE_SEARCH_INDEX', value: azureSearchIndex }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: azureOpenAiEmbeddingDeployment }
            { name: 'WYSZUKIWARKA', value: 'azure' }
            { name: 'AZURE_SEARCH_SEMANTIC', value: azureSearchSemantic }
            // Celowo BRAK CORS_ORIGINS - w Azure przegladarka mowi tylko do uw-web,
            // ktore proxy'uje do uw-api (ingress wewnetrzny, zero CORS). Patrz SPEC_ETAP6.md pkt 5.
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            // Etap 13 - OpenTelemetry -> Application Insights. appInsightsConnectionString
            // jest WYMAGANY, wiec ten env jest zawsze obecny - patrz opis parametru. Nazwa
            // roli (cloud_RoleName) i wykluczenie /zdrowie zawsze ustawione - bez wykluczenia
            // sonda co 15 s (api/main.py:29 z tego samego powodu filtruje access log)
            // zaglusza slady wnioskow w Log Analytics (~5,8 tys. spanow dziennie).
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-cs' }
            { name: 'OTEL_SERVICE_NAME', value: 'uw-api' }
            { name: 'OTEL_PYTHON_FASTAPI_EXCLUDED_URLS', value: 'zdrowie' }
          ]
          // Startup TCP: daje migracjom do ~100 s. Readiness na /zdrowie (Postgres +
          // Blob): rewizja nie dostaje ruchu i nie jest "ready", dopoki zaleznosci nie
          // dzialaja - CI czeka na latestReadyRevisionName. Celowo BEZ liveness na
          // /zdrowie: chwilowa awaria Postgresa restartowalaby kontener w petli.
          probes: [
            {
              type: 'Startup'
              tcpSocket: { port: 8000 }
              periodSeconds: 10
              failureThreshold: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/zdrowie', port: 8000 }
              periodSeconds: 15
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    przypisanieAcrPull
    przypisanieBlobDataContributor
    przypisanieOpenAiUser
    przypisanieDocIntUser
  ]
}

// ---------------------------------------------------------------------------
// Container App frontend - ingress ZEWNETRZNY, Easy Auth dolaczany pozniej
// recznie (infra/README.md pkt d) - `az containerapp auth microsoft update`
// nie ma odpowiednika deklaratywnego w tym pliku bez znajomosci sekretu klienta
// aplikacji Entra, ktory nie moze trafic do Bicepa (sekret).
// ---------------------------------------------------------------------------
resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: nazwaWeb
  location: lokalizacja
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${tozsamosc.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: srodowisko.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: tozsamosc.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'uw-web'
          image: obrazWeb
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            // Wewnatrz srodowiska Container Apps uslugi widza sie po nazwie app
            // (DNS wewnetrzny srodowiska) - stad "uw-api", nie FQDN publiczny.
            { name: 'API_URL_WEWNETRZNY', value: 'http://uw-api' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    przypisanieAcrPull
  ]
}

output uwWebFqdn string = web.properties.configuration.ingress.fqdn
output nazwaRejestru string = acr.name
output clientIdTozsamosci string = tozsamosc.properties.clientId
