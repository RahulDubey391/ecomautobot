# Module 3: Attorney-Vetted Contracts, MSAs, SOWs & Change Order Systems

Most technical freelancers lose margins not from code errors or missed technical benchmarks, but from legal loopholes: ambiguous acceptance criteria, unconditional intellectual property (IP) assignments, soft payment terms, and unbilled scope creep. 

This module provides the complete, production-ready legal framework for executing engineering, architecture, and technical consulting projects at $150+/hour or $10,000+/month retainer tiers.

---

## 1. Legal Architecture: MSA vs. SOW Decoupling

High-ticket technical engagements must decouple legal liability from technical execution. Never execute a single monolithic contract for ongoing or milestone-based technical services.

```
+------------------------------------------------------------------------+
|                   MASTER SERVICES AGREEMENT (MSA)                      |
|  - Invoicing & Net-15 Protocol       - Conditional IP Assignment        |
|  - Mutual Indemnification            - Limitation of Liability Cap     |
|  - Confidentiality & Non-Solicit     - Dispute Resolution & Venue      |
+------------------------------------------------------------------------+
                                    │ Governs All
                                    ▼
+------------------------------------------------------------------------+
|                    STATEMENT OF WORK (SOW-001)                         |
|  - Technical Architecture Scope      - UAT Acceptance Benchmarks       |
|  - Milestone Payments                - Infrastructure Exclusions       |
+------------------------------------------------------------------------+
                                    │ Governs Scope Shifts
                                    ▼
+------------------------------------------------------------------------+
|                     CHANGE ORDER FORMS (COF)                           |
|  - Delta in Architecture Scope       - Budget Adjustments              |
|  - Schedule Impact                   - Client Sign-Off                 |
+------------------------------------------------------------------------+
```

### Strategic Separation Rules

1. **The MSA governs the relationship indefinitely.** It establishes the legal operating environment: warranties, liability caps, dispute venues, IP transfer triggers, and invoicing protocols. It is signed once.
2. **The SOW governs the immediate technical delivery.** It specifies sprint deliverables, architecture definitions, API integrations, and User Acceptance Testing (UAT) criteria. Multiple SOWs can run sequentially or concurrently under one MSA.
3. **The SOW can never override MSA liability limits** unless explicitly citing the exact clause section number of the MSA with an express statement of override signed by both parties.

---

## 2. The Production-Grade Master Services Agreement (MSA)

This agreement is structured specifically for technical contractors, cloud architects, full-stack engineers, and fractional CTOs. 

***

### MASTER SERVICES AGREEMENT

This Master Services Agreement ("**Agreement**") is entered into as of the date of final signature below ("**Effective Date**"), by and between:

* **Contractor:** `{{CONTRACTOR_LEGAL_ENTITY_NAME}}`, a `{{CONTRACTOR_STATE_OF_INCORPORATION}}` `{{LLC/Corporation}}`, with its principal place of business at `{{CONTRACTOR_STREET_ADDRESS}}` ("**Contractor**"), and
* **Client:** `{{CLIENT_LEGAL_ENTITY_NAME}}`, a `{{CLIENT_STATE_OF_INCORPORATION}}` `{{LLC/Corporation}}`, with its principal place of business at `{{CLIENT_STREET_ADDRESS}}` ("**Client**").

Contractor and Client may individually be referred to as a "**Party**" and collectively as the "**Parties**."

#### 1. Engagements and Services
1.1 **Statements of Work.** Contractor shall perform technical and consulting services ("**Services**") described in one or more Statements of Work ("**SOW**") executed by both Parties. Each SOW shall incorporate the terms and conditions of this Agreement. In the event of a direct conflict between this Agreement and any SOW, this Agreement shall govern unless the SOW explicitly identifies the specific section of this Agreement to be superseded.
1.2 **Performance Standards.** Contractor warrants that Services shall be executed in a professional, workmanlike manner compliant with recognized software engineering industry standards. Contractor does not warrant that software deliverables will run entirely error-free or uninterrupted, provided that Deliverables conform in all material respects to the technical specifications defined in the applicable SOW.

#### 2. Invoicing, Payment, and Net-15 Terms
2.1 **Invoicing Cadence.** Unless explicitly altered within an executed SOW, Contractor shall submit invoices bi-weekly or upon the achievement of designated milestones. 
2.2 **Payment Terms.** Client shall remit payment in full within **fifteen (15) calendar days** of the invoice transmission date ("**Net-15**"). All payments shall be made via ACH, electronic wire transfer, or corporate credit card (subject to a 3.5% processing fee passed through to Client).
2.3 **Delinquent Accounts and Suspension.** Invoices unpaid after fifteen (15) days accrue interest at the rate of one and one-half percent (1.5%) per month, or the maximum amount allowed by applicable law, whichever is lower. If Client's account becomes seven (7) or more days delinquent (Day 22 post-invoice), Contractor reserves the contractual right to immediately suspend Services, revoke access to source code repositories and staging environments, and pause development schedules. Contractor shall not be held liable for any damages, launch delays, operational interruptions, or losses incurred by Client resulting from such service suspension.
2.4 **Taxes.** Client shall pay all applicable sales, use, excise, value-added, or other transaction taxes or duties imposed by any governmental authority on the Services and Deliverables provided under this Agreement, excluding taxes based solely on Contractor's net income.

#### 3. Intellectual Property: Conditional Assignment Protocol
3.1 **Background Intellectual Property.** Contractor retains sole and exclusive ownership of all right, title, and interest in and to pre-existing code libraries, tooling, algorithms, templates, software architectures, continuous integration configurations, and standard modules developed prior to the Effective Date or independently of the Services rendered hereunder ("**Contractor Background IP**"). Contractor grants Client a non-exclusive, perpetual, worldwide, fully paid-up, royalty-free license to use, execute, and display Contractor Background IP solely as integrated into or necessary for the operation of the Deliverables.
3.2 **Conditional Assignment of Deliverables.** Conditioned exclusively upon **full, complete, and unencumbered receipt of all payments** due to Contractor under the applicable SOW, Contractor hereby assigns, transfers, and conveys to Client all right, title, and interest in and to the custom software, technical documentation, scripts, and designs explicitly created for Client under such SOW ("**Work Product**"). 
3.3 **Reservation of Rights.** Until all associated invoices for a given phase or milestone are paid in full, Client holds zero ownership, license, or distribution rights to the Work Product. Client shall not deploy, commercialize, reverse engineer, or release Work Product into production environments prior to final payment clearance.
3.4 **Open Source Components.** Client acknowledges that Deliverables may incorporate or interface with open-source software libraries ("**OSS**") licensed under standard community licenses (e.g., MIT, Apache 2.0, BSD). Contractor shall notify Client of any copyleft (e.g., GPL) libraries prior to introduction. Ownership of OSS remains with the respective copyright holders and is governed by the corresponding open-source license terms.

#### 4. Confidentiality and Trade Secrets
4.1 **Definition.** "**Confidential Information**" means any proprietary information, technical data, trade secrets, system designs, product plans, source code, APIs, customer lists, or financial data disclosed by one Party ("**Disclosing Party**") to the other ("**Receiving Party**"), whether orally or in writing, that is designated as confidential or that reasonably should be understood to be confidential.
4.2 **Standard of Care.** Receiving Party agrees to protect Disclosing Party's Confidential Information with the same degree of care it uses for its own confidential assets, but not less than reasonable care. Receiving Party shall not use or disclose any Confidential Information except as necessary to perform obligations under this Agreement.
4.3 **Exclusions.** Confidential Information does not include information that: (a) is or becomes publicly known through no breach of this Agreement; (b) was already known to Receiving Party without restriction; (c) is independently developed without reference to Disclosing Party's Confidential Information; or (d) is required to be disclosed by operation of law or court order, provided Receiving Party gives prompt written notice to allow Disclosing Party to seek a protective order.

#### 5. User Acceptance Testing (UAT) and Defect Remediation
5.1 **Acceptance Window.** Following delivery of any completed Milestone or Deliverable, Client shall have **ten (10) business days** ("**UAT Period**") to test the Deliverable against the acceptance criteria explicitly documented in the SOW.
5.2 **Acceptance Deemed Complete.** If Client fails to provide written notification of specific material non-conformities before 5:00 PM local time on the final day of the UAT Period, or if Client deploys the Deliverable to an end-user-facing production environment, the Deliverable shall be conclusively deemed accepted by Client.
5.3 **Non-Conformity Notice.** Rejection notices must itemize the reproducible steps required to verify the defect and reference the explicit SOW requirement violated. Contractor shall have ten (10) business days to investigate and remediate reproducible material defects, after which the Deliverable shall be resubmitted for a secondary review period of five (5) business days.

#### 6. Warranties and Disclaimers
6.1 **Warranty of Authority.** Each Party represents and warrants that it has full corporate authority to enter into and perform this Agreement.
6.2 **No Third-Party Infringement.** Contractor warrants that, to the best of its knowledge, Work Product created exclusively by Contractor does not infringe upon the valid copyright or trade secret rights of any third party.
6.3 **DISCLAIMER.** EXCEPT AS EXPRESSLY PROVIDED HEREIN, CONTRACTOR MAKES NO WARRANTIES OF ANY KIND, WHETHER EXPRESS, IMPLIED, STATUTORY, OR OTHERWISE, INCLUDING ANY IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, SYSTEM INTEGRATION, OR NON-INFRINGEMENT. CONTRACTOR DOES NOT WARRANT THAT THIRD-PARTY CLOUD PLATFORMS (E.G., AWS, GCP, AZURE), UPSTREAM APIS, OR EXTERNAL HARDWARE WILL REMAIN COMPATIBLE, CONTINUOUS, OR SECURE.

#### 7. Limitation of Liability
7.1 **Consequential Damages Waiver.** NEITHER PARTY SHALL BE LIABLE TO THE OTHER FOR ANY INDIRECT, INCIDENTAL, CONSEQUENTIAL, SPECIAL, PUNITIVE, OR EXEMPLARY DAMAGES (INCLUDING LOSS OF PROFITS, DATA, USE, REVENUE, REPUTATION, OR BUSINESS INTERRUPTION) ARISING OUT OF OR IN CONNECTION WITH THIS AGREEMENT, REGARDLESS OF THE THEORY OF LIABILITY (WHETHER CONTRACT, TORT, STRICT LIABILITY, OR OTHERWISE), EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
7.2 **Aggregate Dollar Cap.** IN NO EVENT SHALL CONTRACTOR'S TOTAL AGGREGATE LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT, THE SERVICES, OR ANY SOW EXCEED THE TOTAL FEES ACTUALLY RECEIVED BY CONTRACTOR FROM CLIENT UNDER THE SPECIFIC SOW GIVING RISE TO THE CLAIM DURING THE SIX (6) MONTH PERIOD IMMEDIATELY PRECEDING THE EVENT GIVING RISE TO LIABILITY.

#### 8. Indemnification
8.1 **By Client.** Client shall defend, indemnify, and hold harmless Contractor, its officers, employees, and subcontractors against any third-party claims, liabilities, damages, or defense costs (including reasonable attorneys' fees) arising out of or related to: (a) Client's data, assets, or software components provided to Contractor; (b) Client's use of Deliverables in violation of applicable laws; or (c) modifications made to Deliverables by parties other than Contractor.
8.2 **By Contractor.** Contractor shall defend and indemnify Client against any third-party claims alleging that Contractor's original Work Product (excluding Client assets, OSS, and third-party APIs) infringes a valid copyright, provided that Client: (a) promptly notifies Contractor in writing; (b) grants Contractor sole control of the defense and settlement; and (c) provides full cooperation.

#### 9. Term and Termination
9.1 **Term.** This Agreement commences on the Effective Date and remains in effect until terminated in accordance with this Section.
9.2 **Termination for Cause.** Either Party may terminate this Agreement or any individual SOW immediately upon written notice if the other Party materially breaches any provision of this Agreement and fails to cure such breach within fourteen (14) calendar days of receiving written notice specifying the breach. Failure to pay valid invoices within the Net-15 window constitutes a material breach.
9.3 **Termination for Convenience.** Unless prohibited by an active SOW, Client may terminate an ongoing SOW for convenience upon providing thirty (30) days' written notice. 
9.4 **Kill Fee / Wind-Down Costs.** If Client terminates an active SOW for convenience, Client shall pay Contractor immediately upon invoice: (a) all fees accrued for work performed through the termination date; (b) any non-cancellable third-party commitments incurred by Contractor on Client's behalf; and (c) a kill fee equal to **twenty-five percent (25%)** of the remaining unbilled contract value of the terminated SOW.

#### 10. Non-Solicitation
During the term of this Agreement and for twelve (12) months following its termination, Client shall not, directly or indirectly, solicit, recruit, employ, or engage as an independent contractor any employee, subcontractor, or key personnel of Contractor who performed Services under this Agreement, without paying Contractor an executive placement fee equal to fifty percent (50%) of the individual's first-year aggregate compensation.

#### 11. General Provisions
11.1 **Governing Law and Dispute Resolution.** This Agreement shall be governed by and construed in accordance with the laws of the State of `{{CONTRACTOR_STATE_OF_GOVERNING_LAW}}`, without regard to its conflict of laws principles. The Parties consent to the exclusive jurisdiction and venue of the state and federal courts located in `{{CONTRACTOR_COUNTY_AND_STATE}}`.
11.2 **Attorneys' Fees.** In any legal action or arbitration brought to enforce the terms of this Agreement, the prevailing Party shall be entitled to recover its reasonable legal expenses and attorneys' fees.
11.3 **Severability.** If any provision of this Agreement is held invalid or unenforceable, that provision shall be reformed to the minimum extent necessary, and the remaining provisions shall continue in full force and effect.
11.4 **Entire Agreement.** This Agreement, together with all executed SOWs and Change Orders, constitutes the final, complete, and exclusive agreement between the Parties with respect to its subject matter and supersedes all prior proposals, negotiations, and representations.

**IN WITNESS WHEREOF**, the Parties hereto have caused this Master Services Agreement to be executed by their duly authorized representatives.

| For: `{{CONTRACTOR_LEGAL_ENTITY_NAME}}` | For: `{{CLIENT_LEGAL_ENTITY_NAME}}` |
| :--- | :--- |
| Signature: ____________________________________ | Signature: ____________________________________ |
| Printed Name: `{{CONTRACTOR_SIGNATORY_NAME}}` | Printed Name: `{{CLIENT_SIGNATORY_NAME}}` |
| Title: `{{CONTRACTOR_SIGNATORY_TITLE}}` | Title: `{{CLIENT_SIGNATORY_TITLE}}` |
| Date: _________________________________________ | Date: _________________________________________ |

***

---

## 3. The Technical Statement of Work (SOW) Template

Attach this concrete SOW to the MSA above. It enforces boundary control, defines exact technical acceptance benchmarks, and eliminates uncompensated API or DevOps debugging.

***

### STATEMENT OF WORK: SOW-202X-001
**Project Identifier:** Cloud Infrastructure Modernization & API Gateway Implementation  
**Governing MSA Effective Date:** `{{DATE_OF_EXECUTED_MSA}}`  
**Client Entity:** `{{CLIENT_LEGAL_ENTITY_NAME}}`  
**Contractor Entity:** `{{CONTRACTOR_LEGAL_ENTITY_NAME}}`  

#### 1. Technical Objective
Contractor shall architect, provision, and deploy a containerized API Gateway running on AWS Elastic Kubernetes Service (EKS), establishing secure reverse-proxy patterns, OAuth2 JWT authorization validation, and CI/CD pipelines via GitHub Actions.

#### 2. Architecture & Deliverables Matrix

| Phase | Deliverable | Scope Specifications & Acceptance Criteria | Target Date |
| :--- | :--- | :--- | :--- |
| **Phase 1** | IaC Repository & EKS Cluster | Terraform scripts to spin up 1 VPC, 3 subnets across 2 AZs, and 1 EKS cluster (v1.28+) with managed node groups. Code passes `terraform validate` and `tfsec`. | Sprint 1 (Week 2) |
| **Phase 2** | Kong Gateway / Auth Integration | Deployment of Kong Ingress Controller via Helm; integration with Client's Auth0 tenant verifying JWT tokens at ingress layer with <15ms latency overhead. | Sprint 2 (Week 4) |
| **Phase 3** | Automated CI/CD Pipeline | GitHub Actions workflow: linting, automated unit test run (`pytest`), containerization to AWS ECR, and Helm-based deploy to staging on merge to `main`. | Sprint 3 (Week 6) |
| **Phase 4** | Documentation & Handover | Architecture diagrams (C4 model), runbooks for operational rollbacks, and a 2-hour technical handover recorded session for engineering staff. | Sprint 4 (Week 7) |

#### 3. Explicit Exclusions (Out-of-Scope)
Any service, task, or environment not explicitly listed in Section 2 is **strictly out of scope**. Exclusions include:
* Migrating downstream legacy microservices to modern framework versions.
* Provisioning, tuning, or indexing client database clusters (RDS PostgreSQL/Aurora).
* Writing unit, integration, or end-to-end tests for client-supplied business logic.
* Purchasing, configuring, or paying for third-party SaaS subscriptions, AWS compute, or domain SSL certificates.
* Resolving defects caused by Client's internal codebases or third-party API downtime.

#### 4. Acceptance Criteria & Benchmark Metrics
Deliverables shall be deemed accepted if they satisfy the following concrete parameters during the 10-day UAT window:
1. **Automated Infrastructure Verification:** `terraform apply` executes without manual terminal interventions or unhandled exceptions in the client-designated staging AWS account.
2. **Gateway Performance Benchmark:** Gateway routes HTTP requests, verifying authorization tokens with p95 response latencies not exceeding 25ms under an automated simulated load of 500 concurrent requests/second over a 10-minute soak test via K6.
3. **Pipeline Health:** The CI/CD pipeline successfully builds, scans, and deploys a sample microservice into staging within a maximum run window of 8 minutes.

#### 5. Technical Dependencies on Client
Contractor shall not be held liable for project delays caused by Client's failure to meet the following dependencies within two (2) business days of request:
* Provisioning AWS IAM Roles with administrative execution bounds for the target staging environment.
* Providing Auth0 administrator API credentials and client tenant metadata.
* Designating a technical point of contact authorized to approve architectural pull requests and merge requests.

#### 6. Compensation and Milestone Schedule
Client shall compensate Contractor a total fixed-fee engagement sum of **$42,000.00 USD**, payable under the following Net-15 schedule:

```
[Phase 1 Deposit: $10,500] ──> Execution of this SOW (Required before kickoff)
[Milestone 2:     $10,500] ──> Acceptance of Phase 1 Infrastructure
[Milestone 3:     $10,500] ──> Acceptance of Phase 2 Gateway Integration
[Milestone 4:     $10,500] ──> Acceptance of Phase 3/4 Pipeline & Final Handover
```

**Signatures Confirming Acceptance:**

| For: `{{CONTRACTOR_LEGAL_ENTITY_NAME}}` | For: `{{CLIENT_LEGAL_ENTITY_NAME}}` |
| :--- | :--- |
| Signature: ____________________________________ | Signature: ____________________________________ |
| Date: _________________________________________ | Date: _________________________________________ |

***

---

## 4. The Zero-Friction Change Order System (COS)

Scope creep occurs when non-technical clients expand features informally via Slack, Zoom, or Jira tickets. Implement the following triage workflow immediately whenever a client requests an update outside the explicit SOW matrix.

```
Client Requests Modification (Slack / Email / Standup)
                       │
                       ▼
         Does it modify architecture, 
         schemas, APIs, or timelines?
                       │
        ┌──────────────┴──────────────┐
       YES                            NO
        │                              │
        ▼                              ▼
Trigger Change Order Protocol     Execute under 
Issue COF Document                Standard Sprint
Do NOT code until signed          Deliverables
```

### 4.1 Production Change Order Form (COF)

***

### CHANGE ORDER REQUEST: CO-202X-001
**Related SOW:** `SOW-202X-001`  
**Client Entity:** `{{CLIENT_LEGAL_ENTITY_NAME}}`  
**Contractor Entity:** `{{CONTRACTOR_LEGAL_ENTITY_NAME}}`  
**Date Submitted:** `{{DATE}}`  
**Change Order Author:** `{{NAME}}`  

#### 1. Scope Modification Description
Client has requested the addition of an internal enterprise Single Sign-On (SSO) integration via SAML 2.0 (Okta) into the Kong Gateway layer, replacing the previously agreed standard OAuth2 JWT-only implementation.

#### 2. Architectural Impact Analysis
* Addition of SAML plugin configuration within Helm charts.
* Creation of custom identity mapping scripts to normalize enterprise assertion attributes.
* Expansion of staging infrastructure mocks to simulate an active Okta Identity Provider (IdP).

#### 3. Budget and Timeline Delta

| Metric | Original Scope | Variance (This CO) | Revised Total |
| :--- | :--- | :--- | :--- |
| **Total Contract Fee** | $42,000.00 | **+$6,500.00** | $48,500.00 |
| **Target Completion Date**| Week 7 (`{{DATE}}`) | **+7 Calendar Days** | Week 8 (`{{DATE}}`) |
| **UAT Window Change** | Unchanged | None | 10 Business Days |

#### 4. Authorization
This Change Order modifies the underlying SOW referenced above. All other terms, conditions, and liability protections of the Master Services Agreement remain in full force. Work on this item will commence solely upon reciprocal signature clearance.

| For: `{{CONTRACTOR_LEGAL_ENTITY_NAME}}` | For: `{{CLIENT_LEGAL_ENTITY_NAME}}` |
| :--- | :--- |
| Signature: ____________________________________ | Signature: ____________________________________ |
| Date: _________________________________________ | Date: _________________________________________ |

***

### 4.2 Out-of-Scope Pushback Scripts

Use these exact copy-paste scripts when clients attempt informal scope-widening.

#### Scenario A: The "Quick Slack Request"
> **Client:** *"Hey, while you're configuring the ingress controller, can you also route our internal legacy analytics subdomains through it? Should just be a quick change in the yaml config, right?"*

**Your Slack/Email Response:**
> "That's a logical expansion for the routing architecture, `{{Client Name}}`. 
>
> However, because our active SOW-001 specifically isolates ingress configuration to the external customer API microservices, evaluating and validating legacy analytics subdomains falls outside our scoped security boundaries and acceptance criteria.
>
> We have two ways forward:
> 1. We keep our current sprint focused entirely on SOW-001 to ensure we hit our scheduled Week 6 launch date.
> 2. I can draft a rapid Change Order to add the analytics routing, which will expand the sprint budget by $2,400 and add 3 business days to our staging verification timeline.
>
> Let me know if you want me to spin up the Change Order, or if we should backlog this for a Phase 2 engagement right after launch."

#### Scenario B: The Standup Meeting Hijack
> **Client:** *"We decided in our leadership sync we want to support both Auth0 and Cognito at the same time for launch. Can you add that in?"*

**Your In-Meeting Verbal Script:**
> "Supporting dual identity providers is definitely feasible from an architectural standpoint, but it fundamentally shifts the authentication pipeline defined in SOW-001. 
> 
> To protect our core release deadline, I'll log that as an out-of-scope architectural change. I will post a formal Change Order summary into the project channel this afternoon outlining the exact delta in hours, cost, and delivery date so you and the leadership team can make an informed trade-off decision."

---

## 5. Automated AI Contract Auditing System

When enterprises supply their own paper, they often insert one-sided clauses: unconditional IP assignment on creation, indefinite warranties, uncapped liability, and Net-60/90 payment terms. 

Use this production prompt to review client-provided MSAs using modern LLMs (Claude 3.5 Sonnet, GPT-4o).

```
System Prompt: High-Ticket Technical Freelance Legal Auditor
```

```markdown
You are an expert commercial technology transactions attorney representing an elite software engineering contractor. You are reviewing a Master Services Agreement (MSA) or Statement of Work (SOW) provided by an enterprise client. 

Analyze the provided contract text with surgical scrutiny. Identify all provisions that expose the contractor to asymmetric commercial, technical, and operational risk.

Review the contract against this non-negotiable Risk Register:

1. INTELLECTUAL PROPERTY GRABS:
   - Identify any clause that assigns IP unconditionally upon *creation* rather than *upon full and final payment*.
   - Identify missing protections for the contractor's Background IP, preexisting codebases, tooling, and developer configurations.
   - Look for broad definitions of "Work Product" that attempt to sweep in independent knowledge, standard libraries, or open-source software.

2. PAYMENT CYCLES & DEFECT DEFICIENCIES:
   - Flag any terms exceeding Net-15 (e.g., Net-30, Net-60, Net-90).
   - Flag clauses where payment is tied to indefinite client "satisfaction" or undefined approval gates without an explicit, time-boxed User Acceptance Testing (UAT) window.
   - Flag the lack of interest on late payments or the lack of an explicit right to suspend services for non-payment.

3. LIABILITY & INDEMNIFICATION TRAPS:
   - Flag any uncapped liability. The liability cap must be mutual and capped strictly at the fees paid to the contractor under the specific SOW in the preceding 6 months.
   - Flag one-way indemnification obligations. Contractor should only indemnify for direct, willful third-party copyright infringement of original work, never for client modifications, third-party APIs, or broad "breach of contract."
   - Flag missing waivers of consequential, special, punitive, and indirect damages.

4. SCOPE AND WARRANTIES:
   - Identify any warranty that Deliverables are "bug-free," "error-free," or guarantee "100% uptime."
   - Identify missing client dependency terms (e.g., delays caused by client's internal team must pause contractor deadlines).

OUTPUT FORMAT REQUIRED:

For every high-risk issue identified, generate a structured markdown response with:
- **Problematic Clause Title & Quoted Text:** [Exact quote from the client's contract]
- **Risk Severity:** [CRITICAL / HIGH / MEDIUM]
- **Asymmetric Risk Assessment:** [Explain explicitly how this clause can bankrupt or cost the contractor unbilled hours/legal exposure]
- **Redline Counter-Draft:** [Provide exact, formal contractual language to replace the clause, balancing the deal in the contractor's favor]
```

---

## 6. Pre-Signature Contract Checklist

Before counter-signing any agreement or commencing development work, run this programmatic check across your engagement documents:

```markdown
### Pre-Flight Contract Execution Checklist

#### Phase 1: Structural Integrity
- [ ] MSA and SOW are decoupled into two distinct documents or clearly segregated exhibits.
- [ ] No work begins without both the MSA and the SOW signed by authorized officers.
- [ ] If the client is using their corporate paper, the AI Review Prompt has been run, redlines applied, and the liability cap negotiated.

#### Phase 2: Cash Flow Engine
- [ ] Payment term is explicitly set to **Net-15** or shorter.
- [ ] Late payment fees are documented (1.5%/month minimum).
- [ ] Clear clause authorizing Contractor to **suspend work and lock repositories** if an invoice is overdue by >7 days.
- [ ] Upfront deposit (minimum 25–50%) has fully cleared into the operating bank account before code execution begins.

#### Phase 3: IP Boundaries
- [ ] Work Product assignment is explicitly **conditional on full and final payment clearance**.
- [ ] Pre-existing code, tools, scaffolding, and libraries are explicitly reserved as **Contractor Background IP**.
- [ ] Open Source Software (OSS) utilization is explicitly permitted without triggering copyleft transfer obligations.

#### Phase 4: Delivery Boundaries
- [ ] SOW lists explicit **Deliverables** and contains a dedicated **Exclusions (Out-of-Scope)** section.
- [ ] Acceptance Testing has a hard, time-boxed cutoff (maximum 10 business days).
- [ ] Automatic acceptance clause triggers if the client remains silent or deploys code to production.
- [ ] Change Order process is specified with cost/timeline adjustment clauses.

#### Phase 5: Risk Containment
- [ ] Mutual waiver of consequential, indirect, and punitive damages.
- [ ] Aggregate liability hard-capped at the value of fees paid to Contractor (or fees paid in the prior 6 months).
- [ ] Non-solicitation protection is included with a predefined 50% first-year placement buyout fee.
- [ ] Governing law and venue set to Contractor's home state and county.
```

Using this contract system protects your technical margin, shields you from catastrophic client liability, forces prompt invoice clearance, and ensures you are fully compensated for every line of code deployed.
