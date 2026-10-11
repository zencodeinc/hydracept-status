# status.hydracept.com go-live runbook

Do not skip steps. Create the public CNAME only after GitHub Pages reports **`protected_domain_state: verified`** for the custom domain, or you risk a dangling `github.io` takeover.

## Trust boundary

Anyone with **write access to the public `hydracept-status` repository** could commit a forged `.hydracept/pages-domain-attestation.json`. The private DNS gate therefore does **not** trust file contents alone: it requires a matching **recent** commit on `main` authored by **`github-actions[bot]`** from the **`pages-domain-attestation`** workflow, with commit time aligned to `attested_at` (minutes, not days). Keep write access limited to deploy keys and trusted admins.

## Why attestation exists

The private `hydracept` repo’s default `GITHUB_TOKEN` **cannot** call `GET /repos/zencodeinc/hydracept-status/pages` (cross-repo Pages API returns 404). The DNS workflow reads the public attestation file via the **Contents API** (optionally authenticated to avoid rate limits) and validates commit metadata via the **Commits API**.

The **public** repo runs **`pages-domain-attestation`** (`workflow_dispatch`). That job passes **`GITHUB_TOKEN: ${{ github.token }}`** with job permissions **`pages: read`** and **`contents: write`**, then requires:

- `build_type == "workflow"` (Pages source must be **GitHub Actions**)
- `cname == status.hydracept.com`
- `protected_domain_state == "verified"` (exactly)
- A **successful** latest **`github-pages`** deployment (`GET /repos/.../deployments?environment=github-pages` + latest status `state: success`). For Actions-built sites, `GET /pages` often returns `"status": null` even after a good deploy — the gate uses deployment evidence instead of legacy `status == "built"`.

Inspect live state (do not bypass the gate):

```bash
gh api repos/zencodeinc/hydracept-status/pages
gh api 'repos/zencodeinc/hydracept-status/deployments?environment=github-pages&per_page=1'
gh api repos/zencodeinc/hydracept-status/deployments/<id>/statuses
```

If `build_type` is `null`, enable Pages → Source → **GitHub Actions**, run **`status-probe`** until deploy succeeds, then re-check. If there is no deployment or the latest status is not `success`, stop — do not hand-edit attestation JSON.

It commits `.hydracept/pages-domain-attestation.json` on `main` (author **`github-actions[bot]`**). The file includes `pages_deployment` (id, sha, created_at, latest status) as **evidence at attestation time**. Attestation must be **fresh** (≤24h, not future-dated) and bound to that commit. The private DNS gate does **not** pin the attested deployment id (status-probe redeploys every few minutes and older ids go inactive); it requires the **current** latest `github-pages` deployment on GitHub to have latest status **`success`** before Porkbun changes.

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

## Probe schedule reliability (prod coloc)

GitHub **`schedule`** on public repos is best-effort and can skip hours. After go-live, prod coloc runs two **5-minute cron** jobs (same block as `coloc-api-watchdog`, installed by `deploy/scripts/coloc-apply-observability.sh`):

| Job | Script | Purpose |
|-----|--------|---------|
| Dispatch | `coloc-status-probe-dispatch.sh` | `workflow_dispatch` **`status-probe`** on `zencodeinc/hydracept-status` when no run is **in progress** (host `flock` + GitHub API). |
| Staleness | `coloc-status-staleness-watchdog.sh` | Fetches `https://status.hydracept.com/status.json`; if older than the host’s **trusted 900s** stale threshold (not `stale_after_seconds` in the JSON), alerts via **ops webhook / Resend ops email** (deduped). |

**Host env** (`.env.coloc` on prod coloc, not GitHub):

| Variable | Purpose |
|----------|---------|
| `HYDRACEPT_STATUS_PAGES_LIVE=1` | Enables both cron jobs (same flag as DNS gate). |
| `HYDRACEPT_STATUS_PROBE_DISPATCH_TOKEN` | Fine-grained PAT: **`actions:write`** on **`zencodeinc/hydracept-status` only** (no repo contents, no org scope). |
| `HYDRACEPT_STATUS_GITHUB_REPO` | Optional override (default `zencodeinc/hydracept-status`). |
| `HYDRACEPT_STATUS_JSON_URL` | Optional override (default `https://status.hydracept.com/status.json`). |

Ops alert dedup state (on the coloc data volume): `status-probe-dispatch-ops.state` and `status-staleness-ops.state`. Failures alert only after **2** consecutive 5-minute checks (configurable). After the first alert, each script sends **at most one alert per hour** (global gap, even when failure classes flap); `dispatch:timeout` and `dispatch:network` count as one **transport** class. A **recovery** notice fires only after an alert was actually sent.

Probes remain **outside-in** (keyless checks inside the public workflow). Coloc only **triggers** that workflow and **monitors** published JSON — it does not invoke paid capabilities or weaken page honesty rules.

**Owner checklist after merge (preferred — no SSH):**

1. Add fine-grained PAT to GitHub **Environment `coloc`** secret `HYDRACEPT_STATUS_PROBE_DISPATCH_TOKEN` (`actions:write` on `zencodeinc/hydracept-status` only).
2. Run **`deploy-coloc`** on prod so the host monorepo checkout is synced to the `main` tip you care about, then dispatch **`coloc-set-status-probe-token`** from that same **`main` commit** (`github.sha` must equal **host git checkout HEAD**, not `HYDRACEPT_DEPLOY_SHA` in `.env.coloc` — that key updates only on **api-target** deploys and can lag after site/app-only deploys). The job uses Azure OIDC + **managed** VM run command: `az vm run-command create` (public `--script` + `--parameters`, token only in **`--protected-parameters status_probe_token_b64=…`**), then `az vm run-command show --instance-view`, then **`az vm run-command delete`** (always). Do **not** use `az vm run-command invoke` for secrets — azure-cli 2.91 **`invoke` has no `--protected-parameters`** and would fail while echoing the value into stderr.
3. GitHub masks the secret; runner/az stderr is filtered before printing; job output is only boolean `VERIFY_*` markers plus `STATUS_PROBE_DISPATCH_OUTCOME=` (`dispatched`, `skipped_active`, `skipped_in_progress`, etc.).
4. Confirm `status-probe-dispatch.log` shows `dispatched` or `skipped_active` / `skipped_in_progress` every ~5m and `status.json` `generated_at` stays fresh. Status-probe crons run on **host Python 3.8+** (stdlib + `scripts/status_probe_*.py`), not the migrate Docker image — host paths must stay valid.

**Azure note:** On Linux, managed run command maps named **parameters** and **protected parameters** to guest environment variables (`expected_deploy_sha`, `hydracept_coloc_repo_dir`, `status_probe_token_b64`). Guest script must not echo secrets. **`show --instance-view`** returns stdout/stderr in `instanceView.output` / `instanceView.error` — the workflow parser whitelists marker lines only. The SHA gate compares `expected_deploy_sha` to **`git rev-parse HEAD`** on the coloc checkout (via `coloc-read-host-checkout-sha.sh`) and requires status-probe deploy scripts on disk. If it fails, markers include `STATUS_PROBE_SHA_EXPECTED` / `STATUS_PROBE_SHA_ACTUAL` and a hint — usually **dispatch before deploy-coloc synced**, or dispatch from a **`main` tip newer/older than the checkout**.

**Do not confuse with `coloc-read-last-deployed-sha.sh`:** that probe (used by **`deploy-coloc`** target detection) resolves the last **full** journal deploy and/or **`HYDRACEPT_DEPLOY_SHA` in `.env.coloc`**. It can read an older API-release SHA while the checkout and `/healthz` already reflect a newer sync — that is expected for narrowed deploys and is **not** what the status-probe token workflow uses.

**Manual fallback (SSH):** mint scoped token → `coloc_upsert_env_coloc` in `.env.coloc` → `bash deploy/scripts/coloc-apply-observability.sh`.

## Steps

1. Merge the hydracept PR (private monorepo = source of truth).
2. Create public repo `zencodeinc/hydracept-status` (`main`). Deploy key (write) on public repo; private key as `HYDRACEPT_STATUS_DEPLOY_KEY` on private hydracept only.
3. Dispatch **sync-hydracept-status** (private). Confirm export on public `main`.
4. **GitHub Pages** — public repo → Source: **GitHub Actions** (required for `build_type: workflow`).
5. **Custom domain** — `status.hydracept.com` in Pages settings.
6. **Org/domain TXT verification** — add **`hydracept.com`** in org **Pages** settings; dispatch **`ensure-status-pages-org-txt`** with GitHub’s `_github-pages-challenge-zencodeinc` host and ~30-char hex token; wait until GitHub shows the org domain **verified**.
7. Public repo: set `HYDRACEPT_STATUS_PAGES_LIVE=1`, run **`status-probe`** once (deploy OK).
8. Public repo: dispatch **`pages-domain-attestation`**; confirm commit on `main` from `github-actions[bot]` and JSON shows `protected_domain_state: verified`, `build_type: workflow`, and `pages_deployment.latest_status.state: success`.
9. Within **24 hours**, private repo: set `HYDRACEPT_STATUS_PAGES_LIVE=1` and `HYDRACEPT_STATUS_PAGES_DOMAIN_VERIFIED=1`, dispatch **`ensure-status-dns`** (Porkbun secrets + `GITHUB_TOKEN` for GitHub API reads).
10. Wait for DNS + HTTPS; verify `https://status.hydracept.com`.
11. Land footer/docs/llms links PR after live verification.

Expected cost: **$0/month** (public Pages + Actions free tier).
