# Security Policy

## Scope

ATS is a **single-user, self-hosted** application — there is no supported
multi-user or public-facing deployment. The web app is designed to run on
`127.0.0.1` only (see `docker-compose.yml`'s port bind and
[`docs/SPEC.md`](./docs/SPEC.md) §3/§4): there is deliberately **no
authentication layer**, because the threat model assumes the only thing that
can reach the app is the operator's own loopback interface. If you expose this
app beyond loopback (a public host, `0.0.0.0`, a reverse proxy without its own
auth, etc.) you are outside the supported threat model and take on that risk
yourself.

The worker (`apps/worker`) runs natively on the host, not in a container, and
talks to external services (board APIs, Ollama, the Codex CLI or Anthropic
API, Telegram) using operator-supplied credentials in a gitignored `.env` /
`config.yaml`. It is not a network-facing service.

## Reporting a Vulnerability

Please use GitHub's **["Report a vulnerability"](https://github.com/drink970082/job-matchbook/security/advisories/new)**
private advisory flow on this repository — this keeps the report out of the
public issue tracker until a fix is available.

If that's not workable, [open an issue](https://github.com/drink970082/job-matchbook/issues/new)
describing the concern without exploit details in the public body; a
maintainer will follow up to move it to a private channel.

There is no bug-bounty program. Given the single-user/loopback scope above,
please size severity accordingly — most theoretical web-app vulnerability
classes (CSRF, XSS against an authenticated session, SSRF from the server
side) matter here only insofar as they'd be reachable by something already on
the operator's own machine or LAN, which is a materially smaller blast radius
than a public multi-tenant service.

## Known Accepted Risks

These are tracked, not overlooked. They stay open because the fix cost (a
major-version upgrade, or an architectural change) outweighs the risk in this
app's single-user, loopback-only deployment model — revisit if that model
ever changes.

- **`next@14.2.35` dependency advisories.** `npm audit --omit=dev` currently
  reports the `next` package as a high-severity finding — three individual GHSA
  advisories roll up into it: DoS via the Image Optimizer's `remotePatterns`
  configuration ([GHSA-9g9p-9gw9-jx7f](https://github.com/advisories/GHSA-9g9p-9gw9-jx7f)),
  HTTP request deserialization DoS with insecure React Server Components
  ([GHSA-h25m-26qc-wcjf](https://github.com/advisories/GHSA-h25m-26qc-wcjf)),
  and HTTP request smuggling in rewrites
  ([GHSA-ggv3-7p47-pfv8](https://github.com/advisories/GHSA-ggv3-7p47-pfv8)) —
  and a moderate finding for `postcss@8.4.31`, a version Next.js 14 bundles
  internally for its own build pipeline (distinct from — and older than — the
  project's own top-level `postcss` dependency, which is already patched).
  All four require the `next@16` major to clear; see `CHANGELOG.md`'s
  `npm audit fix` entry for the exact before/after counts. Accepted because
  these are server-side web-request attack surfaces (DoS, request smuggling)
  that presume a reachable, adversarial network client — not a concern for a
  server that only ever accepts connections from `127.0.0.1`. Revisit at the
  next Next.js major upgrade.
- **`autoheal` holds the Docker socket.** The `autoheal` sidecar mounts
  `/var/run/docker.sock` (root-equivalent host control), pinned by a mutable
  tag. See [`docs/PROGRESS.md`](./docs/PROGRESS.md#open-work) ("`autoheal`
  holds the Docker socket, tag-pinned") for the full writeup.
- **SSRF guard residuals.** The fetch-side SSRF guard (`is_safe_public_url`) is
  a pure, no-DNS string check; a handful of narrow shapes remain unclosed (a
  single read-only redirect GET on the `browser` fetch path, DNS-rebinding,
  and bare internal hostnames that statically resolve internal). See
  [`docs/PROGRESS.md`](./docs/PROGRESS.md#open-work) ("SSRF guard is a pure
  check...") for the full breakdown of what's closed vs. what remains.

## Supported Versions

This project does not maintain long-term-support branches — only the latest
commit on `master`/`dev` is supported. There is no versioned security-patch
backport policy.
