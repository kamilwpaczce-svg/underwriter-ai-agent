# AKS (etap 9b) - jednorazowy klaster pod test chartu

Ten sam chart i ten sam test dymny co na kind, tylko na Azure Kubernetes Service.
Klaster stawiany na jeden wieczor i usuwany tego samego dnia (ok. 0,08 USD/h: wezel
B2als_v2 + Standard LB + publiczny IP + dysk). Wynik i decyzje: `docs/ROZWOJ.md`, Etap 9, AKS (9b).

PowerShell (`$AZ` = pelna sciezka do `az.cmd`):

```powershell
$AZ = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
# jednorazowo na subskrypcji: Microsoft.ContainerService, Microsoft.Compute, Microsoft.Network
& $AZ group create -n rg-underwriter-aks -l swedencentral --tags usunac=<data>
& $AZ aks create -g rg-underwriter-aks -n uw-aks-demo --tier free --node-count 1 `
    --node-vm-size Standard_B2als_v2 --node-osdisk-size 30 `
    --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium `
    --attach-acr uwdemoacrxx1 --no-ssh-key
& $AZ aks get-credentials -g rg-underwriter-aks -n uw-aks-demo
```

Git Bash (z katalogu repo; TAG = pelny SHA commita, ktorego obrazy CI wypchnelo do ACR):

```bash
TAG=$(git rev-parse HEAD)
helm upgrade --install underwriter deploy/helm/underwriter --kube-context uw-aks-demo \
  --wait --wait-for-jobs --timeout 10m \
  --set api.image.repository=uwdemoacrxx1.azurecr.io/uw-api --set api.image.tag=$TAG \
  --set frontend.image.repository=uwdemoacrxx1.azurecr.io/uw-web --set frontend.image.tag=$TAG \
  --set api.corsOrigins=http://localhost:18080

kubectl --context uw-aks-demo port-forward svc/underwriter-frontend 18080:3000 &
KONTEKST=uw-aks-demo HOST=http://localhost:18080 bash deploy/kind/test_dymny.sh
kill %1
```

Sprzatanie (tego samego dnia):

```powershell
& $AZ aks update -g rg-underwriter-aks -n uw-aks-demo --detach-acr uwdemoacrxx1   # inaczej zostaje osierocone AcrPull na ACR
& $AZ group delete -n rg-underwriter-aks --yes                                     # usuwa tez grupe MC_rg-underwriter-aks_*
kubectl config delete-context uw-aks-demo; kubectl config delete-cluster uw-aks-demo
```
