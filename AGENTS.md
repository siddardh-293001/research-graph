# ResearchGraph working agreement

- Build sections according to `docs/BUILD_PLAN.md` and the user's latest steering.
- The user requests self-verification for Section 6 and all subsequent sections.
  Extend `src.verify` for new functionality, run meaningful checks, and retain
  evidence and limitations before reporting a section complete.
- Publish verified source and portable project additions to
  `https://github.com/siddardh-293001/research-graph` and keep that repository
  updated for future additions, as explicitly authorized by the user.
- Publish no credentials, `.env` files, private caches or duplicate generated
  runs. Frozen public metadata and derived serving artifacts are authorized for
  this repository. Keep original local legacy artifacts intact.
- Hosting must use free plans only. No paid credits, subscriptions, compute,
  persistent disks or inference services are authorized. The target is Render's
  confirmed `My Workspace` (`tea-dbb5bjnavr4c73fvbs30`) on `plan: free`, one
  instance. The user confirmed no payment method is attached.
- A local test pass does not prove a public deployment is live. Verify the
  deployed commit, release hash, HTTP/UI behavior and actual resource limits.
