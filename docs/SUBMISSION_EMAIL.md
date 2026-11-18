# Submission email (draft)

Fill in the three bracketed items before sending. Do not send until the live URL has been tested.

---

**To:** careers@darglobal.co.uk
**Subject:** Technical Assignment Submission: Junior AI Engineer (Applied AI) – [Your Full Name]

Dear DarGlobal Recruitment Team,

Please find my submission for the Junior AI Engineer (Applied AI) technical assignment.

**PropIntel AI – Real Estate Intelligence Assistant**

- Live application: [LIVE URL]
- Source code: [GITHUB REPOSITORY URL]
- API documentation: [LIVE URL]/api/docs

The application answers real estate questions using public information collected from darglobal.co.uk and
wasalt.sa. Each answer cites its sources, states which website a fact came from, and declines when the data
does not cover the question.

How it meets the brief:

1. **Scraping:** separate scrapers for both sites that follow robots.txt and Wasalt's llms.txt policy.
2. **Chatbot:** retrieval-augmented generation with hybrid search (vector and BM25, merged with Reciprocal
   Rank Fusion), metadata filters, conversation history and validated citations.
3. **OpenRouter:** free models with timeouts, retries and an automatic fallback chain.
4. **Docker:** one multi-stage image containing the API, the web interface and the prebuilt knowledge base.
5. **Deployment:** publicly hosted at the URL above.

Two things I would like to be upfront about:

- Wasalt's bot protection blocked automated collection part-way through. I did not work around it, so the
  Wasalt data covers 21 listings in one Riyadh district. DarGlobal coverage is 38 projects, 14 press
  releases and 9 corporate pages. The README explains this and how coverage can be widened compliantly.
- The application is on a free hosting tier, so the first request after a period of inactivity can take
  about a minute while the service wakes up.

The repository includes an evaluation report with measured retrieval and answer-quality results, 60
automated tests, and setup instructions. Suggested questions to try:

- Which projects does DarGlobal have in Oman?
- What did DarGlobal announce about Jeddah in November 2026?
- Show me 3-bedroom apartments for sale in Riyadh under SAR 800,000
- What is the mortgage rate in Saudi Arabia? (it should decline to answer)

Thank you for the opportunity. I would be glad to walk through the design decisions in an interview.

Kind regards,
[Your Full Name]
[Phone number] | [LinkedIn or portfolio link]
