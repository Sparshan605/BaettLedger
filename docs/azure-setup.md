# BaettLedger — Azure Setup

**Owner: Protsahan** · You provision infrastructure. You write no application code.
Shivang deploys code into what you create. Sparshan's Pi talks to it.

Demo: **August 19, 2026.** Everything here should be done by **August 15**.

---

## 1. What you are building

Nine Azure resources in one resource group. Your job is done when Shivang can deploy
code and it runs, and when nothing is costing money we did not expect.

| # | Resource | Service | Tier | Why |
|---|---|---|---|---|
| 1 | `rg-baettledger` | Resource group | — | Everything in one place, delete in one command |
| 2 | `stbaettledger` | Storage account | Standard LRS | Photos, and the Function App needs one anyway |
| 3 | `kv-baettledger` | Key Vault | Standard | Connection strings, per proposal §9 |
| 4 | `appi-baettledger` | Application Insights | Free tier | Traces + errors, per proposal §9 |
| 5 | `sql-baettledger` | Azure SQL Database | **Basic, NOT serverless** | See the warning below |
| 6 | `func-baettledger` | Function App | Consumption, Python 3.11 | The API |
| 7 | `cv-baettledger` | Azure AI Vision | **F0 (free)** | Detects devices in photos |
| 8 | `aif-baettledger` | AI Foundry project | Pay-as-you-go | Hosts the Count Agent |
| 9 | `swa-baettledger` | Static Web Apps | Free | The dashboard |

### Do not use SQL serverless

Serverless auto-pauses after an hour idle and takes **~60 seconds to wake**. On demo day
that is indistinguishable from a total failure, in front of guests. **Basic tier (~$7/mo)
never pauses.** This is the single most important choice on this page.

---

## 2. Create them, in this order

Order matters — later resources reference earlier ones.

```bash
# Variables — change nothing else in this file
RG=rg-baettledger
LOC=canadacentral
SA=stbaettledger        # must be globally unique, lowercase, no dashes
SQLSRV=sqlsrv-baettledger   # must be globally unique
```

```bash
# 1. Resource group
az group create --name $RG --location $LOC
```

```bash
# 2. Storage account + the photos container
az storage account create --name $SA --resource-group $RG --location $LOC --sku Standard_LRS
az storage container create --name photos --account-name $SA --auth-mode login
```

```bash
# 3. Key Vault
az keyvault create --name kv-baettledger --resource-group $RG --location $LOC
```

```bash
# 4. Application Insights
az monitor app-insights component create --app appi-baettledger --location $LOC --resource-group $RG
```

```bash
# 5. SQL server + Basic database. Pick a strong admin password and put it in Key Vault, not in chat.
az sql server create --name $SQLSRV --resource-group $RG --location $LOC \
  --admin-user baettadmin --admin-password '<SET-A-STRONG-PASSWORD>'
az sql db create --resource-group $RG --server $SQLSRV --name baettledger --service-objective Basic
```

```bash
# 6. Allow Azure services (the Function App) to reach SQL
az sql server firewall-rule create --resource-group $RG --server $SQLSRV \
  --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
```

```bash
# 7. Function App (Python, consumption plan)
az functionapp create --resource-group $RG --name func-baettledger \
  --storage-account $SA --consumption-plan-location $LOC \
  --runtime python --runtime-version 3.11 --functions-version 4 \
  --app-insights appi-baettledger
```

```bash
# 8. Azure AI Vision on the FREE tier
az cognitiveservices account create --name cv-baettledger --resource-group $RG \
  --kind ComputerVision --sku F0 --location $LOC --yes
```

**9. AI Foundry** and **10. Static Web Apps** are easier in the portal than the CLI.
For Foundry: create a project, deploy a small chat model (`gpt-4o-mini` or equivalent),
and give Shivang the endpoint + key. For Static Web Apps: create it on the Free plan and
connect it to the GitHub repo — it will ask which branch and which folder.

> Verify flags against current Azure docs if a command errors. CLI syntax drifts between versions
> and it is faster to check than to guess.

---

## 3. Secrets

**Nothing goes in the repository.** Ever. Proposal §9 commits us to Key Vault and a secret scan.

Put these four in Key Vault:

| Secret name | Value |
|---|---|
| `sql-connection-string` | From the SQL DB → Connection strings → ODBC |
| `storage-connection-string` | From the storage account → Access keys |
| `vision-key` | From the Vision resource → Keys and Endpoint |
| `foundry-key` | From the Foundry project |

```bash
az keyvault secret set --vault-name kv-baettledger --name sql-connection-string --value '<value>'
```

Then let the Function App read them without storing them:

```bash
# Give the Function App a managed identity
az functionapp identity assign --name func-baettledger --resource-group $RG

# Grant that identity read access to secrets (use the principalId the command above printed)
az keyvault set-policy --name kv-baettledger --object-id <principalId> --secret-permissions get list
```

### The device key

The Pi authenticates with one shared secret. **You generate it and hand it to Sparshan.**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Store it as Function App setting `DEVICE_KEY`. Send it to Sparshan privately — not in the
repo, not in a group chat that gets screenshotted. He puts it in the Pi's `.env`.

> **Why a shared key and not Entra ID**, since the proposal §9 says Entra: the Pi is a headless
> device with no human at a browser, so it cannot complete an interactive sign-in. A device key
> is the normal pattern for this. Worth being able to say out loud if a guest asks.

---

## 4. Cost control — do this on day one

Azure for Students gives $100 and **no automatic stop**. Expected run rate is $15–25/month;
a mistake can be much more.

1. **Set a spending cap.** Portal → Subscription → *Spending limit* → On.
2. **Set a budget alert** at $25 and $50.

```bash
az consumption budget create --budget-name baett-monthly --amount 40 \
  --time-grain Monthly --category Cost
```

3. Keep Vision on **F0**. It is free up to 20 calls/minute and 5,000/month. A demo uses maybe 50.

---

## 5. Photo retention — 90 days

Proposal §8 commits to purging photos after 90 days, and §9 repeats it. Set the lifecycle rule
on the `photos` container: **delete blobs 90 days after creation.** Portal → Storage account →
Lifecycle management → Add rule. One rule, one condition. Takes two minutes and it is a graded
commitment, so do not skip it.

---

## 6. You are done when

- [ ] All nine resources exist in `rg-baettledger`
- [ ] `https://func-baettledger.azurewebsites.net` returns something (even a 404 — it means it is alive)
- [ ] Shivang can deploy to the Function App
- [ ] Shivang can read all four secrets from Key Vault using the managed identity
- [ ] Sparshan has the `DEVICE_KEY` and the function URL
- [ ] Spending cap is on and a budget alert exists
- [ ] The 90-day lifecycle rule is on the `photos` container
- [ ] Application Insights is receiving traces from the Function App

**The last two bullets that matter most, on August 13:** the Function App existing, and
Sparshan having a URL and a key. Everything else can follow. Sparshan's uploader is blocked
until those exist, and he cannot test the Pi end of the system without them.

---

## 7. If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| Storage account name rejected | Not globally unique | Add digits: `stbaettledger605` |
| Function App won't start | Runtime mismatch | Confirm Python 3.11, functions-version 4 |
| Function can't reach SQL | Firewall | Re-check the `AllowAzureServices` rule above |
| Function can't read Key Vault | Missing policy | Re-run `az keyvault set-policy` with the right objectId |
| Vision returns 401 | Wrong key or region | Key and endpoint must be from the same resource |
| Everything is slow the first call | Consumption cold start | Expected. Warm it before the demo — see the runbook |
