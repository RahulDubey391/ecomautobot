# Module 4: 50-Point CRO Audit Rubric, A/B Testing Matrix & Launch Checklist

This module provides the operational framework to audit, launch, and optimize high-converting B2B and SaaS landing pages. It contains zero theoretical filler: every section contains scoring models, executable scripts, prioritization matrices, or testing workflows ready for immediate deployment.

---

## 1. The 50-Point Heuristic CRO Pre-Launch Rubric

Evaluate your landing page across five functional domains. Score each item using this scale:
*   **0 = Deficient / Missing:** Element does not exist or fails industry usability standards.
*   **1 = Acceptable:** Element exists but introduces friction, lacks clarity, or misses secondary optimizations.
*   **2 = Optimized:** Element executes flawlessly according to empirical conversion benchmarks.

**Target Benchmarks:**
*   **90–100:** Enterprise/Production Ready. Expected baseline conversion: 4.5%–8.5% (cold traffic to primary trial/demo action).
*   **75–89:** Solid. Viable for soft-launch with minor friction points.
*   **< 75:** Do not allocate paid acquisition traffic. Significant conversion leaks present.

### Domain 1: Above-the-Fold & First-Screen Clarity (Points 1–10)

| ID | Audit Point | Scoring Criteria (Score 2 Requirements) | Weight | Score (0-2) |
| :--- | :--- | :--- | :--- | :--- |
| **01** | **5-Second Value Test** | A cold visitor can identify what the product does, who it is for, and the primary benefit within 5 seconds without scrolling. | 2x | |
| **02** | **Category Anchor** | Sub-headline explicitly states the product category (e.g., "SOC-2 Compliance Automation Platform") instead of vague metaphors. | 1x | |
| **03** | **Pain-to-Outcome Delta** | Headline quantifies or clearly outlines the shift from current negative state to desired end state. | 1x | |
| **04** | **Primary CTA Dominance** | The main CTA button uses a high-contrast accent color not used elsewhere on the screen except for conversion actions. | 2x | |
| **05** | **Frictionless CTA Copy** | CTA copy states the direct outcome rather than a generic verb (e.g., "Generate Your API Key" vs. "Submit"). | 1x | |
| **06** | **Risk-Reversal Microcopy** | Explicit statement directly beneath the primary CTA eliminates immediate purchase anxiety (e.g., "14-day trial • No credit card required • 2-minute setup"). | 1x | |
| **07** | **Product Reality Anchor** | Hero media is an actual high-fidelity interface screenshot, interactive product preview, or animated walkthrough—not an abstract vector illustration. | 2x | |
| **08** | **Navigation Isolation** | Main navigation is stripped of exit links (e.g., no generic "Blog", "About Us", or social media icons). Retains only "Features", "Pricing", "Docs", and "Login". | 1x | |
| **09** | **Viewport Preservation** | At 1440x900 and 375x812 resolutions, the entire Hero section (Headline, Subhead, CTA, Trust Banner) renders completely above the fold without forced scrolling. | 1x | |
| **10** | **Baseline Latency Visuals** | Hero image/video utilizes priority hints (`fetchpriority="high"`), optimized WebP/AVIF formats, and explicitly reserved dimensions to prevent layout shifts. | 1x | |

### Domain 2: Social Proof & Trust Architecture (Points 11–20)

| ID | Audit Point | Scoring Criteria (Score 2 Requirements) | Weight | Score (0-2) |
| :--- | :--- | :--- | :--- | :--- |
| **11** | **Customer Logo Authority** | 5–8 recognizable customer/integration logos appear directly beneath the hero section in full monochrome/consistent opacity. | 1x | |
| **12** | **Verified Testimonials** | Testimonials include full name, high-resolution headshot, job title, company logo, and verified LinkedIn reference or company URL. | 1x | |
| **13** | **Metric-Driven Proof** | Social proof quotes include specific, quantitative outcomes (e.g., "Reduced pipeline latency by 43%") rather than vague praise ("Great tool!"). | 2x | |
| **14** | **Security & Compliance Badges** | Industry certifications (SOC-2 Type II, ISO 27001, GDPR, HIPAA) are displayed with active verification links or recognizable badge assets. | 1x | |
| **15** | **Third-Party Review Ratings** | G2, Capterra, or Trustpilot aggregate badges display live score ratings (e.g., "4.8/5 stars based on 240+ reviews") with recognizable star iconography. | 1x | |
| **16** | **Contextual Proof Placement** | Social proof elements are distributed across the page directly adjacent to friction points (e.g., security badge directly under pricing tables). | 2x | |
| **17** | **Case Study Micro-Cards** | Deep-dive mini-cards include: Problem, Solution, Quantified Outcome, and a link to the complete customer teardown. | 1x | |
| **18** | **Real-Time Usage Telemetry** | Aggregate platform utilization metrics are displayed (e.g., "$1.2B processed", "14M queries handled daily"). | 1x | |
| **19** | **Press / Media Inclusion** | Mentions from Tier-1 trade publications or venture funding coverage feature specific editorial quotes rather than just isolated publication logos. | 1x | |
| **20** | **Identity Alignment** | The displayed customer personas (industry, company size) match the targeted audience profile of the inbound traffic source. | 1x | |

### Domain 3: UX, Visual Hierarchy & Cognitive Load (Points 21–30)

| ID | Audit Point | Scoring Criteria (Score 2 Requirements) | Weight | Score (0-2) |
| :--- | :--- | :--- | :--- | :--- |
| **21** | **Single Visual Path** | The layout follows an alternating Z-pattern or strict single-column F-pattern without chaotic visual breaks or overlapping elements. | 1x | |
| **22** | **Scannable Typography** | Strict typography scale: Body text is 16px–18px with 1.5–1.6 line-height; headings maintain a clear mathematical hierarchy (H1 > H2 > H3). | 1x | |
| **23** | **Micro-Headings over Labels** | Feature blocks use benefit-driven subheads (e.g., "Deploy in 3 clicks") rather than structural labels ("Feature 1"). | 1x | |
| **24** | **Whitespace Breathing Room** | Section padding defaults to at least 80px–120px on desktop to provide visual separation and prevent cognitive fatigue. | 1x | |
| **25** | **Frictionless Sticky Header** | Sticky navigation includes only the logo, a single primary CTA button, and optionally a "Sign In" link; height remains under 70px. | 1x | |
| **26** | **Contrast Ratio Compliance** | Text-to-background contrast conforms to WCAG 2.1 AA requirements (minimum 4.5:1 for body copy, 3:1 for large headers). | 1x | |
| **27** | **Interactive Demonstrations** | Complex product features are conveyed via tabs, interactive toggles, or sandbox UI components rather than passive wall-of-text blocks. | 2x | |
| **28** | **Zero Competing Choices** | Each page section drives toward a single logical action; the page eliminates secondary distracting links (e.g., social channel icons). | 2x | |
| **29** | **Predictable Scroll Anchor Links** | Anchor links smoothly scroll to expected target sections with an offset applied so the sticky header does not obscure section headings. | 1x | |
| **30** | **FAQ Accordion Implementation** | Objections are addressed via clean, accessible accordions; schema markup (`FAQPage`) is embedded in JSON-LD. | 1x | |

### Domain 4: Conversion Mechanics & Form Optimization (Points 31–40)

| ID | Audit Point | Scoring Criteria (Score 2 Requirements) | Weight | Score (0-2) |
| :--- | :--- | :--- | :--- | :--- |
| **31** | **Field Minimization** | Top-of-funnel signup requires only 1 to 3 fields (Business Email, Password, or direct OAuth / Google SSO / GitHub SSO). | 2x | |
| **32** | **Inline Real-Time Validation** | Form fields run validation asynchronously on blur (`onBlur`), displaying green checks for valid input or actionable error messages before submission. | 1x | |
| **33** | **Work Email Detection** | Form script automatically flags free webmail addresses (`@gmail.com`, `@yahoo.com`) in real-time if the page targets B2B enterprise leads. | 1x | |
| **34** | **Autofill & Input Types** | Input tags leverage strict HTML5 `type` and `autocomplete` attributes (`type="email"`, `autocomplete="work email"`, `type="tel"`). | 1x | |
| **35** | **SSO Friction Reduction** | "Sign Up with Google" / "Sign Up with GitHub" OAuth buttons sit above the manual email input field, cutting signup latency to 1 click. | 2x | |
| **36** | **Form State Indicators** | The submit button features explicit disabled/loading states (spinner + "Creating account...") upon click to eliminate duplicate submissions. | 1x | |
| **37** | **Exit-Intent Interceptor** | A non-blocking overlay or banner activates on desktop cursor exit with an alternative low-friction offer (e.g., self-guided interactive tour or PDF playbook). | 1x | |
| **38** | **Contextual Pricing Toggles** | If pricing is displayed, monthly vs. annual pricing clearly highlights savings (e.g., "Save 20%") with the toggle default set to the preferred plan. | 1x | |
| **39** | **Secondary CTA De-escalation** | Visitors not ready to convert are offered an explicit lower-friction secondary path (e.g., "Watch 3-minute interactive demo") instead of leaving. | 1x | |
| **40** | **Dynamic Post-Submission Path** | Form redirects immediately to an actionable onboarding flow, personalized schedule page (Chili Piper/Calendly), or app dashboard rather than a static "Thank you" page. | 1x | |

### Domain 5: Technical Performance, Mobile & Accessibility (Points 41–50)

| ID | Audit Point | Scoring Criteria (Score 2 Requirements) | Weight | Score (0-2) |
| :--- | :--- | :--- | :--- | :--- |
| **41** | **Largest Contentful Paint (LCP)** | LCP renders under 2.0 seconds on a simulated 4G mobile connection (verified via PageSpeed Insights / Lighthouse). | 2x | |
| **42** | **Cumulative Layout Shift (CLS)** | CLS maintains a strict score below 0.05 throughout page load, image rendering, and script execution. | 1x | |
| **43** | **Interaction to Next Paint (INP)** | Page interactions (accordions, modal opens, form inputs) register an INP under 200 milliseconds. | 1x | |
| **44** | **Mobile Touch Targets** | All interactive elements (CTA buttons, inputs, links) measure at least 48x48px with 8px+ clearance around surrounding elements. | 1x | |
| **45** | **Responsive Typography Scaling** | Fluid typography using CSS `clamp()` prevents horizontal scroll or oversized headline wrapping across small displays (320px–375px). | 1x | |
| **46** | **Script Deferment & Tag Manager** | All non-critical tracking scripts, marketing pixels, and customer chat widgets are deferred or loaded via Google Tag Manager asynchronously. | 1x | |
| **47** | **Zero Broken Assets & Console Logs** | Developer console logs zero 4xx/5xx network errors, zero uncaught JavaScript exceptions, and zero broken image/font paths. | 1x | |
| **48** | **Native Form Fallback Resilience** | Forms function correctly without JavaScript enabled (standard `POST` endpoint fallback) or fail gracefully with clear warnings. | 1x | |
| **49** | **Keyboard Navigability** | The entire conversion flow (tabs, accordion, modal, form inputs, submit button) is fully navigable using the `Tab` and `Enter` keys with clear focus rings. | 1x | |
| **50** | **UTM Attribution Persistence** | UTM parameters (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`) are stored in session cookies/LocalStorage and passed via hidden form fields. | 2x | |

---

## 2. High-Velocity A/B Testing Prioritization Matrix (PXL Framework)

Do not run tests based on subjective opinions. Use this modified, SaaS-specific **PXL Framework** to prioritize variations based on impact potential, behavioral science, and execution velocity.

### The Standardized Hypothesis Formula

Every test entered into the prioritization matrix must strictly adhere to the following syntax:

```text
BECAUSE we have observed [Quantitative Metric / Qualitative Observation] in [Tool: Hotjar/GA4/Database],
WE PREDICT THAT changing [Independent Variable / Element] into [Specific New Variation]
WILL RESULT IN [Expected Outcome / Primary Metric Shift]
BECAUSE [Psychological Principle / Friction Removal Rationale].
```

**Example:**
> "BECAUSE we have observed a 64% drop-off on the step 2 signup field in GA4, WE PREDICT THAT changing the 5-field registration form into a 1-click Google/GitHub OAuth layout WILL RESULT IN a 22% increase in completed signups BECAUSE it removes high-friction manual data entry on mobile devices."

### The SaaS PXL Scoring Engine

Rate each prospective test across these 10 binary and weighted variables:

| Evaluation Vector | Scoring Rule | Score (0 or 1) |
| :--- | :--- | :--- |
| **1. Above the Fold?** | Is the primary modification visible immediately without scrolling? (Yes = 1, No = 0) | |
| **2. High-Noticeability?** | Will 80%+ of visitors notice the change within 3 seconds? (Yes = 1, No = 0) | |
| **3. Motivation vs. Friction?** | Does the test directly add user motivation or remove an explicit barrier to entry? (Yes = 1, No = 0) | |
| **4. Backed by Data?** | Is this test derived from quantitative data (heatmaps, drop-off analytics)? (Yes = 1, No = 0) | |
| **5. Backed by User Feedback?** | Is this supported by direct customer quotes, sales calls, or surveys? (Yes = 1, No = 0) | |
| **6. Directly Affects Primary Metric?**| Does the test alter the core conversion step rather than a micro-metric? (Yes = 1, No = 0) | |
| **7. Copy / Offer Focused?** | Does the test iterate on copy, value proposition, or offer mechanics (higher impact than styling/color)? (Yes = 1, No = 0) | |
| **8. Strategic Leverage?** | Can the winning variation be applied across other funnels/landing pages? (Yes = 1, No = 0) | |
| **9. Dev Simplicity (Weighted)** | **Effort Score:** Can this be built and fully QA'd in < 4 hours? (Yes = 2, 4–12 hours = 1, > 12 hours = 0) | (0–2) |
| **10. Low Tracking Complexity** | Does the test use existing GA4 events without requiring custom backend event tracking? (Yes = 1, No = 0) | |
| **TOTAL SCORE** | **Maximum Possible Score: 11 points** | **/ 11** |

### Prioritization Decision Rules
*   **Scores 9–11:** High Velocity — Schedule for immediate deployment in the upcoming test sprint.
*   **Scores 6–8:** Medium Priority — Queue for execution once higher-scoring tests conclude.
*   **Scores < 6:** Low Priority / Discard — High engineering overhead with low conversion leverage.

### Pre-Calculated Sample Size & Minimum Detectable Effect (MDE) Table

To ensure statistical power ($1 - \beta = 0.80$) with a significance level of $\alpha = 0.05$ (95% Confidence):

| Baseline Conversion Rate | Desired MDE: 5% Lift | Desired MDE: 10% Lift | Desired MDE: 20% Lift |
| :--- | :--- | :--- | :--- |
| **2.0%** | 312,000 visitors / variant | 78,000 visitors / variant | 19,500 visitors / variant |
| **4.0%** | 154,000 visitors / variant | 38,500 visitors / variant | 9,600 visitors / variant |
| **6.0%** | 101,000 visitors / variant | 25,200 visitors / variant | 6,300 visitors / variant |
| **8.0%** | 74,000 visitors / variant | 18,500 visitors / variant | 4,650 visitors / variant |
| **10.0%** | 58,000 visitors / variant | 14,500 visitors / variant | 3,650 visitors / variant |

*Rule of thumb:* Do not launch an A/B test if your monthly page volume cannot hit the required sample size per variant within **28 consecutive days**. Running tests past 30 days introduces sample pollution via cookie expiration and user habituation.

---

## 3. Production Pre-Launch QA Checklist

Run this operational checklist within 24 hours of moving any landing page into production.

### A. Tracking, Attribution & Analytics Verification

- [ ] **GA4 Config Tag:** Fires once and only once on initial page load. DebugView confirms page view parameters (`page_location`, `page_title`).
- [ ] **Custom Event Verification:** All CTA buttons fire a unified event:
  ```javascript
  gtag('event', 'conversion_intent', {
    'cta_location': 'hero_primary',
    'cta_text': 'Start Free Trial',
    'page_path': window.location.pathname
  });
  ```
- [ ] **Ad Platform Pixels:** Meta Pixel (`Lead`), Google Ads Conversion Tag (`Submit lead form`), LinkedIn Insight Tag are confirmed firing via Chrome Extension debuggers (Meta Pixel Helper, Tag Assistant).
- [ ] **UTM Parameter Ingestion:** Landing page extracts URL search params and injects them into hidden form inputs.
- [ ] **Data Layer Object:** Pre-submission data pushed cleanly to `window.dataLayer`:
  ```javascript
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({
    'event': 'form_interaction',
    'form_id': 'lead_capture_main',
    'step': 'submission_attempt'
  });
  ```

### B. Cross-Device & Viewport Functional Testing

- [ ] **iOS Safari:** Verify sticky headers do not obscure inputs when the virtual keyboard expands; verify no automatic zooming occurs on input focus (all form fields must have `font-size: 16px` or larger).
- [ ] **Android Chrome:** Verify back-button handling, form input autofill compatibility, and bottom bar anchoring.
- [ ] **Desktop Ultrawide (2560x1440):** Verify layout max-width containers (e.g., `max-w-7xl`) prevent content from stretching across the screen.
- [ ] **Desktop Standard (1440x900 & 1920x1080):** Confirm the complete hero section renders above the 800px vertical threshold.
- [ ] **Mobile Narrow (375x667 - iPhone SE):** Verify headline does not wrap into more than 4 lines; check that horizontal scrolling is impossible (`overflow-x: hidden` enforced on body).

### C. Console QA Script

Open Chrome Developer Tools on your staging/production page, paste this complete script into the **Console**, and press Enter. It automatically checks for common technical CRO failures:

```javascript
(function runCROTechnicalAudit() {
  console.group("%c CRO Automated DOM & Pixel Pre-Launch Check", "background: #111; color: #4ade80; font-size: 14px; font-weight: bold; padding: 4px;");

  const results = [];
  
  // 1. Verify Viewport Meta Tag
  const viewportMeta = document.querySelector('meta[name="viewport"]');
  results.push({
    Test: "Viewport Configuration",
    Status: viewportMeta && viewportMeta.content.includes("width=device-width") ? "PASS" : "FAIL",
    Details: viewportMeta ? viewportMeta.content : "Missing viewport meta tag"
  });

  // 2. Form Input Font-Sizes (Prevents iOS Zoom)
  const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), select, textarea'));
  const smallInputs = inputs.filter(el => {
    const fontSize = parseFloat(window.getComputedStyle(el).fontSize);
    return fontSize < 16;
  });
  results.push({
    Test: "Input Font-Size >= 16px (iOS Zoom Prevention)",
    Status: smallInputs.length === 0 ? "PASS" : "FAIL",
    Details: smallInputs.length === 0 ? "All inputs compliant" : `${smallInputs.length} inputs have font-size < 16px`
  });

  // 3. Image Optimization & Dimensions
  const images = Array.from(document.querySelectorAll('img'));
  const missingDimensions = images.filter(img => !img.hasAttribute('width') || !img.hasAttribute('height'));
  results.push({
    Test: "Images with Explicit Dimensions (CLS Prevention)",
    Status: missingDimensions.length === 0 ? "PASS" : "WARN",
    Details: missingDimensions.length === 0 ? "All images have width/height" : `${missingDimensions.length} images missing width/height attributes`
  });

  // 4. Analytics & GTM Detection
  const hasGTM = !!window.google_tag_manager;
  const hasGA4 = typeof window.gtag === 'function' || !!window.dataLayer;
  results.push({
    Test: "Tag Manager / DataLayer Initialization",
    Status: (hasGTM || hasGA4) ? "PASS" : "FAIL",
    Details: `GTM Found: ${hasGTM} | dataLayer Found: ${hasGA4}`
  });

  // 5. Button & Form Integrity
  const forms = Array.from(document.querySelectorAll('form'));
  const orphanButtons = Array.from(document.querySelectorAll('button')).filter(btn => {
    return btn.type === 'submit' && !btn.closest('form');
  });
  results.push({
    Test: "Submit Button Integrity",
    Status: orphanButtons.length === 0 ? "PASS" : "FAIL",
    Details: orphanButtons.length === 0 ? `Validated ${forms.length} forms correctly wired` : `${orphanButtons.length} submit buttons exist outside forms`
  });

  // 6. Broken Anchor Links
  const links = Array.from(document.querySelectorAll('a[href^="#"]'));
  const brokenAnchors = links.filter(link => {
    const targetId = link.getAttribute('href').slice(1);
    return targetId.length > 0 && !document.getElementById(targetId);
  });
  results.push({
    Test: "Anchor Link Integrity",
    Status: brokenAnchors.length === 0 ? "PASS" : "FAIL",
    Details: brokenAnchors.length === 0 ? "All internal page anchors link to valid IDs" : `${brokenAnchors.length} anchor links point to missing elements`
  });

  console.table(results);
  console.groupEnd();
})();
```

---

## 4. Post-Launch CRO Diagnostics & Troubleshooting Playbook

When conversion rates miss baseline expectations post-launch, consult this triage engine.

```
                   [POST-LAUNCH METRICS DIVERGENCE DETECTED]
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
   [High Bounce Rate (>75%)]                             [Low Conversion Rate]
   [Low Dwell Time (<20s)]                               [Adequate Dwell Time (>60s)]
            │                                                     │
    ┌───────┴───────┐                                     ┌───────┴───────┐
    ▼               ▼                                     ▼               ▼
[Traffic Mismatch] [Technical Crash]              [High CTA Click /]   [Zero CTA Clicks]
(Check Referral /  (Check JS Console &            [Low Form Submit]    (Value Proposition
 Search Intent)     Mobile Render Speed)                  │             Failure)
                                                          │
                                                  ┌───────┴───────┐
                                                  ▼               ▼
                                           [Form Friction]   [Offer Anxiety /]
                                           (Validation bugs, [No Risk-Reversal]
                                            too many fields)
```

### Symptom-Diagnosis-Remediation Matrix

| Symptom / Metric Signature | Root Cause Diagnosis | Remediation Action Plan | Verification Step |
| :--- | :--- | :--- | :--- |
| **High Bounce (>75%), Dwell Time < 15s** | Message Match Failure: The headline does not match the ad copy or search intent that drove the click. | Update the Hero headline to directly mirror the highest-volume ad headline verbatim. Remove generic welcome copy. | Compare Google Ads/Meta Ads exact headline text with H1 copy. |
| **Mobile CR is < 25% of Desktop CR** | Responsive input friction or viewport displacement. | Strip all non-essential copy above the mobile fold. Convert multi-field forms into a 1-click Google Auth button or 2-step micro-funnel. | Run simulated mobile throttling sessions on low-end devices. |
| **High CTA Clicks (>10%), Low Form Completions (<15%)** | Form Friction / Unannounced Roadblock (e.g., asking for Credit Card unexpectedly, password complexity errors). | Add micro-copy directly above the form: "No credit card required. Instant 60-second setup." Implement inline validation to show errors immediately. | Review Hotjar/PostHog session replays filtered specifically by `Form Abandonment`. |
| **Dwell Time > 90s, CTA Clicks < 1.5%** | Analysis Paralysis: The page provides too much unstructured technical copy without a clear, compelling offer next step. | Condense feature lists into tabbed switchers. Introduce a sticky bottom conversion bar that triggers after the user scrolls 40% down the page. | Inspect scroll-depth tracking events at 25%, 50%, 75%, and 100%. |
| **Sudden Metric Cliff-Drop (CR drops > 50% overnight)** | Deployment Regression: Tracking tags dropped off during deploy, or an API key/webhook expired. | Verify form submissions hit your CRM/database directly. Check the network panel for `500 Internal Server Error` on API endpoints. | Submit a test lead using `cro_test@yourcompany.com` and trace the execution path. |

### Session Replay Analysis Protocol (PostHog / Hotjar / FullStory)

Do not watch replays randomly. Execute this structured 5-step auditing session:

1.  **Configure Filters:**
    *   *Event:* Visited Landing Page
    *   *Filter 1:* Duration > 15 seconds (removes immediate bounces)
    *   *Filter 2:* Target Actions: Clicked CTA button OR Scrolled > 50%
2.  **Tag Rage Clicks & Dead Clicks:**
    *   Filter for elements where users clicked 3+ times within a 1-second window. This isolates non-clickable images, static badges, or broken links that users assume are interactive.
3.  **Form Funnel Drop-off Scrubbing:**
    *   Watch 20 consecutive recordings of users who focused on the first form field but failed to submit.
    *   Document the exact input field where cursor movement stalls or where the user exits.
4.  **Device-Specific Segmentation:**
    *   Review desktop and mobile sessions separately. Mobile analysis must specifically monitor layout shifts that occur when the keyboard opens.
5.  **Audit Log Synthesis:**
    *   Log observations in a friction register:

```markdown
### Friction Log Entry Template
- **Timestamp / Session URL:** [Insert Link]
- **Device / Screen Resolution:** [e.g., iPhone 14 Pro / 393x852]
- **Observed Behavior:** User tapped 4x on the customer logo expecting a case study link.
- **Hypothesis:** Customer logo looks like an active interactive card.
- **Recommended Fix:** Add subtle grayscale filter or explicitly link logo to external case study modal.
```

---

## 5. Automated CRO Review Prompt (LLM Heuristic Auditor)

Use the following system prompt to audit your landing page copy, structural hierarchy, and objection architecture. Run this prompt within any advanced LLM by providing the complete HTML code or raw copy of your landing page.

```markdown
You are an elite conversion rate optimization (CRO) consultant and direct-response SaaS copywriter. Your task is to rigorously critique and audit the provided SaaS landing page copy and HTML against empirical conversion standards.

Analyze the landing page using the following 5 dimensions:
1. Above-the-fold value clarity (5-second rule, category anchor, clear transformation delta).
2. Social proof mechanics (placement, specificity, metric-driven proof, objection mitigation).
3. Cognitive load and visual hierarchy (scannability, single conversion goal, information chunking).
4
