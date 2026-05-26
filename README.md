# Katalyst Team — CRM Dashboard

Internal listings / owners dashboard (React + Vite). Deployed on [Vercel](https://vercel.com) from this repo.

**Live app:** connect your Vercel project to this repository with **Root Directory** = `real-estate-crm-dashboard-react`.

## Local workspace vs GitHub

| Location | What lives there |
|----------|------------------|
| This repo (`katalystteam` on GitHub) | `real-estate-crm-dashboard-react/` only |
| Your Desktop `katalyst/` folder | Dashboard **plus** GHL scripts, CSV exports, site HTML, etc. (ignored by git) |

To push dashboard changes from your machine:

```bash
cd /path/to/katalyst
git add real-estate-crm-dashboard-react/
git status   # confirm only dashboard files are staged
git commit -m "Describe your change"
git push origin main
```

Vercel redeploys automatically after each push to `main`.

## Refresh dashboard data (local)

From `real-estate-crm-dashboard-react/` with `.env` configured (see `.env.example`):

```bash
npm run sync:clickup          # ClickUp → dashboardData.ts
npm run sync:ghl-engagement   # GHL email engagement
```

Then commit `src/data/generated/*.ts` if you want teammates / Vercel to see the update.

## Develop

```bash
cd real-estate-crm-dashboard-react
npm install
npm run dev
```
