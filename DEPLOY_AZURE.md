# Deploy HeatWatch to Azure App Service (free tier)

Goal: a public demo link for the judges, e.g. `https://seaguard-heatwatch.azurewebsites.net/demo`.

## Option 1: from GitHub (recommended)
1. Azure Portal → **Create a resource** → **Web App**.
2. Basics:
   - Subscription: your free account · Resource group: `heatwatch-rg` (new)
   - Name: `seaguard-heatwatch` (must be unique)
   - Publish: **Code** · Runtime stack: **Python 3.12** · OS: **Linux**
   - Region: **UAE North** (or the nearest available)
   - Pricing plan: **Free F1** (no cost, never expires)
3. Deployment tab → **Continuous deployment: Enable** → sign in to GitHub → pick the repo and branch `main`.
4. Review + create. Wait about 3 minutes.
5. Web App → **Configuration** → **General settings** → **Startup command**:
   `python -m uvicorn app:app --host 0.0.0.0 --port 8000`
   Save, then **Restart**.
6. Open `https://<name>.azurewebsites.net/demo`. Health check: `/health`.

## Option 2: container (Container Apps), if F1 is not enough
`Dockerfile` builds the whole app (`/demo`, `/worker`, `/api/...`).

## Cost safety
- F1 is free. Still set **Cost Management → Budgets → US$5** with an email alert.
- The US$200 trial credit lasts 30 days. When the portal asks, upgrade to pay-as-you-go
  **before** day 30 so the account is not disabled during judging; the F1 app stays free.

## Before submitting
- Open `/demo` on a phone and a laptop; run the Guided tour once.
- Label stays visible: all data is SIMULATED.
