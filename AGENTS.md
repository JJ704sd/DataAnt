# DataAnt Agent Rules

## Real-network live runs

- Real Douban access requires the operator's explicit `--live-approved` flag.
- Every live command must include `--max-queries N`, where `1 <= N <= 10`.
- Live runs must use `--headed` and `--min-interval 5` or greater.
- Stop immediately on CAPTCHA, rate limiting, `sec.douban.com`, login security checks, or `BLOCKED`.
- When the browser is redirected to the `sec.douban.com` proof-of-work challenge page (`<form name="sec">` + `name="cha"` + `name="sol"` markers), the run writes `SITE_PROTECTION_CHALLENGE` and stops. The browser could solve the SHA-512 nonce in 1-3 seconds, but the project never waits for it: that would be automating a site-protection bypass. The operator waits for the IP frequency window to expire (typically 15-30 minutes) and reruns.
- Never automate login, CAPTCHA solving, or site-protection bypasses.
- Never use `--retry-status BLOCKED`. `--retry-status SITE_PROTECTION_CHALLENGE` is also forbidden for the same reason.
- Keep browser profiles, cookies, sessions, HTML, screenshots, logs, evidence, and workbooks out of Git.

## Offline CI

- CI must never invoke `--live-approved`, launch a live browser, or access `movie.douban.com`.
- Only `.gitkeep` placeholders may be tracked under `browser-profile/`, `outputs/`, and `artifacts/`.

## Scope

These rules apply to the repository root and every subdirectory unless a more specific `AGENTS.md` strengthens them. A nested file may not weaken the real-network or artifact rules.
