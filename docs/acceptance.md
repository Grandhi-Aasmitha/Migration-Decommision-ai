# Manual-upload acceptance checklist

- A fresh workspace opens with zero documents and an empty graph. Restarting never imports a test corpus.
- Upload a source PDF, DOCX, or TXT with application ID and version. Processing finishes or reports a useful error.
- Its graph contains the uploaded document, passages, and application. Extracted domain facts add systems, capabilities, and policy obligations.
- Node/connection details show the correct source excerpt, document/chunk reference, PDF page or section, and original-file link.
- Graph filters exclude other application evidence; applicable shared policy/NFR documents may remain.
- Re-uploading identical bytes/metadata does not duplicate documents or graph evidence.
- Q&A cites uploaded evidence and acknowledges missing information.
- Target assessment pauses for priority, compares documented matches/gaps, and reports missing targets honestly.
- Paused assessments and user uploads survive restart. No example documents appear.

The local demo recognizes fixed fact lines and otherwise displays document structure/excerpts. Evaluate natural-language extraction, relevance, abstention, and adversarial instructions with Ollama before accepting AI-generated facts or assessments.

Regression documents under `backend/tests/fixtures/documents/` are test-only resources. The application does not package, serve, or auto-upload them. Business owners must validate their own uploaded evidence and agree the assessment's open checks before adopting a recommendation.
