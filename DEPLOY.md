# Deploy — do this now, Aug 13

## Prereqs (from Protsahan)
- `func-baettledger` Function App already exists in `rg-baettledger`
- You have the `DEVICE_KEY` value
- You can read the four Key Vault secrets, or Protsahan sets these as
  Function App settings directly (Key Vault references) — either works.

## 1. Install the Azure Functions Core Tools (once, on your machine)
```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

## 2. Log in and set app settings
```bash
az login
az functionapp config appsettings set --name func-baettledger --resource-group rg-baettledger \
  --settings DEVICE_KEY="<value from Protsahan>"
# Repeat for SQL_CONNECTION_STRING, STORAGE_CONNECTION_STRING, VISION_ENDPOINT,
# VISION_KEY, FOUNDRY_ENDPOINT, FOUNDRY_KEY once you have them (Aug 14-16 is fine
# for these — DEVICE_KEY is the only one the §0 stub needs today).
```

## 3. Deploy
From inside this folder:
```bash
func azure functionapp publish func-baettledger
```

## 4. Verify immediately
```bash
curl https://func-baettledger.azurewebsites.net/api/health
# -> {"status":"ok"}

curl -X POST https://func-baettledger.azurewebsites.net/api/events \
  -H "x-device-key: wrong-key"
# -> 401 {"error":"bad key"}
```

## 5. Tell Sparshan
The moment `/api/health` responds, message him the base URL and confirm he has
the `DEVICE_KEY`. He is blocked until this step.

---

## After today (Aug 14 onward)
1. Run `schema.sql` against `sql-baettledger` (Query editor in the portal, or
   `sqlcmd` / Azure Data Studio).
2. Add the remaining app settings (`SQL_CONNECTION_STRING`, etc.) as they
   become available from Protsahan.
3. Redeploy with `func azure functionapp publish func-baettledger` — every
   endpoint in `function_app.py` is already written, so nothing else changes
   as secrets land; it'll just start working end-to-end.
4. Run the 10-step test in `docs/api.md` §8.
