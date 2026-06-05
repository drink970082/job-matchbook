# web (ats-web)

The Next.js 14 web app of the ATS project — tracker UI, dashboards, Server
Actions, and the Prisma/SQLite data layer. One of two services in this repo
(the other is [`../worker`](../worker)).

See the [root README](../../README.md) for the project overview, architecture,
stack, Docker instructions, and data model.

## Quick start

```bash
npm install
npx prisma generate
npm run dev
```

Open http://localhost:3000.

## Scripts

- `npm run dev` — dev server
- `npm run build` — production build
- `npm start` — run production build
- `npm run lint` — ESLint
- `npm test` — Jest
