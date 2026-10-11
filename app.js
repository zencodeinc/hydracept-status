/** Hydracept public status page — reads probe JSON only; never upgrades status client-side. */

import { bootstrapStatusPage } from "./status_page_dom.mjs";

bootstrapStatusPage(document, fetch.bind(globalThis), Date.now());
