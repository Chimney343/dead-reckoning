# Anti-bot techniques for the Three Decks crawler: research and decision

Status: decided 2026-10-04. **None of these techniques is adopted.** This note records what each one is, how Cloudflare detects it, and why it is not used, so the question does not have to be reopened from scratch. It is deliberately not an implementation plan: it has no configuration, code or tool choices.

## 1. Context

- **What the crawl has met so far.** About 1,500 ship pages on 3–4 October 2026, with no 403, no 429 and no challenge. Every ordinary page carries Cloudflare's JavaScript detection script (`/cdn-cgi/challenge-platform/scripts/jsd/main.js`), so Cloudflare is profiling clients, but it has had no reason to act.
- **The bottleneck.** Throughput is set by the 5-second rate, at about 12 pages a minute. None of the techniques below changes that.

## 2. The techniques

### 2.1 Rotating User-Agents

| | |
|---|---|
| What it is | Sending a different browser-like User-Agent per request or session, so requests cannot be grouped as one crawler. |
| How it is detected | Cloudflare compares layers of each request. A User-Agent that claims Chrome while the TLS handshake (JA3/JA4 fingerprint) and the HTTP/2 settings show a Python client is a mismatch, and the mismatch itself raises the bot score. A disguised Scrapy client stands out more than an honest one. |
| Cost | Free. |
| Risk here | The owner could no longer see, contact or throttle the crawler. Makes challenges more likely, not less. |
| Instead | Identify more clearly, not less: the User-Agent and `From:` header already carry the contact (done), and Web Bot Auth (section 3) proves identity cryptographically. |

### 2.2 Proxies: datacenter, residential, mobile, Tor

| | |
|---|---|
| What it is | Routing requests through many IP addresses so per-IP limits and bans do not apply. |
| How it is detected | IP reputation: datacenter networks and Tor exits are flagged and often challenged outright. Residential addresses are harder to spot, which is what they are sold for. |
| Cost | Residential and mobile bandwidth is paid per gigabyte; Tor is free but mostly challenged. |
| Risk here | Hides the source, so the owner cannot tell how the crawler behaves. Residential pools route traffic through other people's devices, and consent is often weak or absent: in July 2026 the FBI seized NetNut's domains after Google's Threat Intelligence Group estimated its network at about 2 million botnet devices. Buyers inherit the GDPR exposure. |
| Instead | Ask the owner for an IP Access "Allow" rule for the one IP the crawl uses (section 3). |

### 2.3 TLS and HTTP/2 fingerprint impersonation

| | |
|---|---|
| What it is | HTTP clients that reproduce a real browser's TLS handshake and HTTP/2 settings, so the JA3/JA4 fingerprint matches the claimed browser. |
| How it is detected | An arms race. Cloudflare scores JA4 together with the User-Agent, HTTP/2 behaviour and request patterns; every layer has to agree, and keeping them agreeing is ongoing work. |
| Cost | Libraries are free; keeping up with browser releases is not. |
| Risk here | Its only purpose is to pass as a human's browser: the same breach as 2.1, done more thoroughly. |
| Instead | Not needed: an honest client has not been challenged. |

### 2.4 Headless and "stealth" browsers

| | |
|---|---|
| What it is | Driving a real browser engine, with patches that hide the signs of automation. |
| How it is detected | Cloudflare's challenges and JavaScript detections probe `navigator.webdriver`, DevTools-protocol traces, canvas and WebGL output (a server with no GPU reports a software renderer), installed fonts and screen metrics. |
| Cost | Heavy: a browser per page in CPU and memory, slower and brittle. Three Decks needs no JavaScript to render its data (plan 3.1), so a browser adds nothing to what is extracted. |
| Risk here | Disguise again, and it would run Cloudflare's detection script on every page instead of ignoring it. |
| Instead | Not needed. |

### 2.5 Challenge and CAPTCHA solving

| | |
|---|---|
| What it is | Getting past a Cloudflare challenge or Turnstile widget, either in a disguised browser or by paying a solving service (human workers or models) for tokens. |
| How it is detected | The challenge is itself the detection; tokens are tied to the session and client. |
| Cost | Per-solve fees and added latency. |
| Risk here | It only ever happens after the site has asked the client to prove itself, so it overrides the site's decision. It likely breaches Cloudflare's and the site's terms, and circumventing an access control carries legal risk. |
| Instead | Stop, as the crawler already does (cool-offs, then a `blocked` close), and ask the owner. |

## 3. What to do instead

In order of value:

1. **Ask for an export** of the ship catalogue. It removes Tier C's ~30,000 pages entirely.
2. **Ask for a faster rate**, e.g. one request every 2 s. With the owner's consent it is one settings change, and Tier C drops from about 2 days to under a day.
3. **Ask for an IP Access "Allow" rule** for the crawl's IP. Cloudflare's Bot Fight Mode cannot be skipped by WAF custom rules; an IP Access rule that matches first is the documented exemption. Super Bot Fight Mode (paid plans) also supports skip rules.
4. **Identify cryptographically with Web Bot Auth.** Implemented 2026-10-05 (anti-bot hardening plan): `threedecks/wba.py` signs every wire-bound request with HTTP Message Signatures (RFC 9421) using an Ed25519 key (`@authority` and `signature-agent` covered, tag `web-bot-auth`, short expiry), `scripts/wba_keygen.py` generates the key and public directory, and `scripts/wba_directory.py` emits a signed directory response. It stays off until `THREEDECKS_WBA_KEY` and `THREEDECKS_WBA_DIRECTORY` are set. Cloudflare's verified-bot bar is honest self-identification plus obeying `robots.txt` and crawl delays at reasonable rates, which this crawler already meets. Whether the owner can act on verified or signed bots depends on his Cloudflare plan.

   **Pending (manual): hosting the directory and registering it with Cloudflare.**

   1. Generate the production key (`scripts/wba_keygen.py`); keep the private key out of git (it lives under `data/`, which is gitignored).
   2. Host the directory at `/.well-known/http-message-signatures-directory` — a tiny Worker that signs per request is preferred (fresh `created`/`expires`); static hosting with a long `expires` is the fallback. Validate with Cloudflare's `http-signature-directory` CLI.
   3. Cloudflare dashboard → Manage Account → Configurations → Bot Submission Form → Verification Method "Request Signature" → paste the directory URL and the UA match pattern (`dead-reckoning/0.1`).
   4. Confirm via crawltest: `https://crawltest.com/cdn-cgi/web-bot-auth` returns 200 after registration (401 means the format is fine but the key is unknown; 400 means a formatting bug).
   5. Optionally tell the site owner.
5. **Keep what works:** honest User-Agent and `From:` header, 5 s between requests, `robots.txt`, cool-offs, and stopping on a block.

## 4. When to revisit

Only if the site owner asks for the crawler to behave differently. Any change that hides the crawler would need his written consent, and with his consent the owner-side options in section 3 are simpler and more reliable than any of section 2.

## Sources

- [Scrapy docs: Common Practices, "Avoiding getting banned"](https://docs.scrapy.org/en/latest/topics/practices.html)
- [Cloudflare: Bot Fight Mode](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/)
- [Cloudflare: Verified bots](https://developers.cloudflare.com/bots/concepts/bot/verified-bots/)
- [Cloudflare: Web Bot Auth](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth)
- [Cloudflare blog: The age of agents: cryptographically recognizing agent traffic](https://blog.cloudflare.com/signed-agents/)
- [Cloudflare blog: Bot Management heuristics](https://blog.cloudflare.com/bots-heuristics/)
- [Scrapfly: JA3/JA4 TLS fingerprinting](https://scrapfly.io/blog/posts/ja3-ja4-tls-fingerprinting-guide-to-detection-and-evasion)
- [krowdev: How websites detect bots in 2026 (JA4 and HTTP/2)](https://krowdev.com/article/bot-detection-2026/)
- [Crawlex: How Cloudflare uses TLS and HTTP/2 fingerprints in bot scoring](https://blog.crawlex.net/blog/cloudflare-tls-http2-fingerprinting/)
- [Browserless: Turnstile detection and limits](https://www.browserless.io/blog/turnstile-bypass)
- [Crawlex: How proxy networks source IPs](https://blog.crawlex.net/blog/how-proxy-networks-source-ips/)
- [Shifter: The malware economy behind cheap residential proxies](https://shifter.io/blog/malware-sourced-residential-proxies)
- [StackHarbor: Cloudflare allowlist strategy](https://stackharbor.com/en/knowledge-base/cfops-allowlist-strategy-waf-ip-access/)
