# status.hydracept.com go-live runbook

Do not skip steps. Create the public CNAME only after GitHub Pages reports **`protected_domain_state: verified`** for the custom domain, or you risk a dangling `github.io` takeover.

## Trust boundary

Anyone with **write access to the public `hydracept-status` repository** could commit a forged `.hydracept/pages-domain-attestation.json`. The private DNS gate therefore does **not** trust file contents alone: it requires a matching **recent** commit on `main` authored by **`github-actions[bot]`** from the **`pages-domain-attestation`** workflow, with commit time aligned to `attested_at` (minutes, not days). Keep write access limited to deploy keys and trusted admins.

## Why attestation exists

The private `hydracept` repo’s default `GITHUB_TOKEN` **cannot** call `GET /repos/zencodeinc/hydracept-status/pages` (cross-repo Pages API returns 404). The DNS workflow reads the public attestation file via the **Contents API** (optionally authenticated to avoid rate limits) and validates commit metadata via the **Commits API**.

The **public** repo runs **`pages-domain-attestation`** (`workflow_dispatch`). That job uses **this repo’s** `GITHUB_TOKEN` (`pages: read`) and requires:

- `status == "built"`
- `build_type == "workflow"` (Pages source must be **GitHub Actions**)
- `status == "built"` (not `null`, `building`, or `errored`)

**If `status` or `build_type` is `null` at attestation time:** inspect live Pages state (do not bypass the gate):

```bash
gh api repos/zencodeinc/hydracept-status/pages
```

Expected before attestation: `"status":"built"` and `"build_type":"workflow"`. If either is `null`, stop — enable Pages → Source → **GitHub Actions**, run **`status-probe`** until deploy succeeds, then re-check the API. If the API still shows `null` after a green deploy, **stop and ask for a reviewed relaxation**; do not commit a hand-edited attestation or weaken the gate locally.
- `cname == status.hydracept.com`
- `protected_domain_state == "verified"` (exactly)

It commits `.hydracept/pages-domain-attestation.json` on `main`. Attestation must be **fresh** (≤24h, not future-dated) and bound to that commit.

## Org-level domain verification (TXT)

GitHub org **Pages domain verification** uses a **TXT** record at `_github-pages-challenge-zencodeinc.hydracept.com` with the hex token shown in the org **Pages → Add domain** UI.

**Agents run this step** on the private `hydracept` repo (no new Porkbun keys):

1. In the **zencodeinc** org **Settings → Pages**, add apex domain **`hydracept.com`** (org verification TXT is tied to the org challenge host, not `status.hydracept.com`).
2. Copy the **host label** (`_github-pages-challenge-zencodeinc`) and **TXT value** from GitHub (~**30 lowercase hex characters**, no quotes).
3. Dispatch **`ensure-status-pages-org-txt`** (private repo) with those inputs. The workflow only creates/replaces **TXT** at that label; it does not touch the `status` CNAME or any other records.
4. Wait for DNS propagation, then complete verification in GitHub. The **`status` CNAME** (`ensure-status-dns`) still requires the public attestation gate **after** Pages shows the custom domain verified — TXT verification comes first.

## Repository variables (per repo)

| Variable | Repository | Purpose |
|----------|------------|---------|
| `HYDRACEPT_STATUS_PAGES_LIVE=1` | **Public** `hydracept-status` | Enables `status-probe` (build + deploy). |
| `HYDRACEPT_STATUS_PAGES_LIVE=1` | **Private** `hydracept` | Required before `ensure-status-dns`. |
| `HYDRACEPT_STATUS_PAGES_DOMAIN_VERIFIED=1` | **Private** `hydracept` | Manual attestation after GitHub UI shows domain verified. |

Probe persistence: orphan branch **`probe-data`**, one commit force-pushed each run (shallow fetch). Monorepo sync never copies `data/` on the public repo.

**Stale window:** data older than **3× probe interval** (default 900s) → unknown; HTTP `Date` on `status.json` is the clock.

## Steps

1. Merge the hydracept PR (private monorepo = source of truth).
2. Create public repo `zencodeinc/hydracept-status` (`main`). Deploy key (write) on public repo; private key as `HYDRACEPT_STATUS_DEPLOY_KEY` on private hydracept only.
3. Dispatch **sync-hydracept-status** (private). Confirm export on public `main`.
4. **GitHub Pages** — public repo → Source: **GitHub Actions** (required for `build_type: workflow`).
5. **Custom domain** — `status.hydracept.com` in Pages settings.
6. **Org/domain TXT verification** — add **`hydracept.com`** in org **Pages** settings; dispatch **`ensure-status-pages-org-txt`** with GitHub’s `_github-pages-challenge-zencodeinc` host and ~30-char hex token; wait until GitHub shows the org domain **verified**.
7. Public repo: set `HYDRACEPT_STATUS_PAGES_LIVE=1`, run **`status-probe`** once (deploy OK).
8. Public repo: dispatch **`pages-domain-attestation`**; confirm commit on `main` from `github-actions[bot]` and JSON shows `protected_domain_state: verified`, `build_type: workflow`.
9. Within **24 hours**, private repo: set `HYDRACEPT_STATUS_PAGES_LIVE=1` and `HYDRACEPT_STATUS_PAGES_DOMAIN_VERIFIED=1`, dispatch **`ensure-status-dns`** (Porkbun secrets + `GITHUB_TOKEN` for GitHub API reads).
10. Wait for DNS + HTTPS; verify `https://status.hydracept.com`.
11. Land footer/docs/llms links PR after live verification.

Expected cost: **$0/month** (public Pages + Actions free tier).
