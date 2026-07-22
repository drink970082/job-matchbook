# Security Policy

## Scope

Job Matchbook is a **single-user, self-hosted** application — there is no supported
multi-user or public-facing deployment. The web app is designed to run on
`127.0.0.1` only (see `docker-compose.yml`'s port bind and
[`docs/SPEC.md`](./docs/SPEC.md) §6/§11): there is deliberately **no
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

Some risks are knowingly carried rather than fixed, because the fix cost (a
major-version upgrade, or an architectural change) outweighs the risk in this
app's single-user, loopback-only deployment model. They are enumerated — each
with what is closed, what remains, and why it is acceptable — in
[**`docs/SPEC.md` §11**](./docs/SPEC.md#11-non-functional-requirements),
"Accepted security residuals". At the time of writing they cover the `next@14`
dependency advisories, the `autoheal` sidecar's Docker-socket mount, the SSRF
guard's no-DNS residual shapes, and JD prompt-injection blast radius.

Anything with a route to closure is tracked in
[`docs/PROGRESS.md`](./docs/PROGRESS.md#open-work).

## Supported Versions

This project does not maintain long-term-support branches — only the latest
commit on `main` is supported. There is no versioned security-patch backport
policy.
