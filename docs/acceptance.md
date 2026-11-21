# Sample acceptance guide

The seven UTF-8 files in `samples/` describe Ledger Core, Atlas, Nova, a shared security policy, and a service NFR. They contain no customer data. `manifest.json` supplies metadata consistently to the loader.

| Check | Expected evidence/result |
| --- | --- |
| Source dependencies | Identity Gateway, Enterprise Event Bus, Archive Store, with source citations |
| Source capabilities | Transaction posting, reconciliation, audit export |
| Atlas coverage | Three capabilities; Identity Gateway and Enterprise Event Bus; Archive Store evidence missing |
| Nova coverage | Posting and audit export; all three integrations; reconciliation evidence missing |
| Balanced fixture ranking | Atlas 90%, Nova 77% |
| Integration-priority fixture ranking | Nova 87%, Atlas 80% |
| Policy answer | Seven-year audit retention, access controls, encryption, privileged-action recording; original policy cited |
| Recovery answer | Four-hour recovery and fifteen-minute data-loss objective; service NFR cited; target compliance unverified |
| Source-only corpus | No preferred target; comparison not yet possible |
| Unanswerable cost question | Missing cost evidence acknowledged; no invented estimate |
| Clarification | Assessment pauses, remains paused after API restart, resumes with the selected objective |
| Citation review | Excerpt and original document agree; DOCX/TXT section references do not invent PDF pages |

Demo Q&A deliberately returns source excerpts or explicit fixture graph facts. Natural-language relevance and abstention must also be evaluated with Ollama mode, including cost questions and adversarial document instructions. The system validates citation IDs and quoted extraction spans; that alone does not establish the truth of every generated sentence.

Before adopting this dataset as accepted: have an application owner verify the dependency/capability inventory, a target owner confirm coverage gaps, and security/operations owners agree the open policy/NFR checks. Record their decisions in the team's review process. The software does not claim that this agreement has already happened.
