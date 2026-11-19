# web (ats-web)

The Next.js 14 web app of the ATS project — tracker UI, dashboards, Server
Actions, and the Prisma/SQLite data layer. One of two services in this repo
(the other is [`../worker`](../worker)).

See the [root README](../../README.md) for the project overview and
[`docs/SETUP.md`](../../docs/SETUP.md) for Docker and the other setup paths. The data
model is [SPEC §8](../../docs/SPEC.md#8-data-model); Prisma owns the schema
(`prisma/schema.prisma`).

## Quick start

```bash
npm install
npx prisma generate
npx prisma db push      # create/sync the SQLite schema (`make db-push` from the root)
npm run dev
```

Open http://localhost:3000.

## Scripts

- `npm run dev` — dev server
- `npm run build` — production build
- `npm start` — run production build
- `npm run lint` — ESLint
- `npm test` — Jest
