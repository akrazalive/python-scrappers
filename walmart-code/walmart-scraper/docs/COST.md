# Monthly Operating Cost (one location, twice weekly)

Assumptions: 11 categories → ~250–400 leaf listings, ~25k–40k unique local products, listing pages + product pages
for UPC. About 9 runs per month.

| Item | Basis | Estimate / month |
|---|---|---|
| Data-access API (Oxylabs Web API, Walmart endpoint) | listing + product pages per run × 9 runs; see observed figures below | **$80 – $250** |
| Azure Container Apps Job | ~3–6 h × 1 vCPU / 2 GiB × 9 runs (consumption plan, free grant applies) | $0 – $10 |
| Azure Blob Storage | < 5 GB incl. versions | ~$1 |
| Key Vault | a few hundred operations | < $1 |
| Log Analytics | < 1 GB ingestion | $0 – $3 |
| **Total** | | **≈ $85 – $265** |

Cost levers: `crawl.enrich_product_pages: false` removes most product-page requests (UPC then only when listed),
cutting provider cost by roughly 60–70 %. Each extra location adds roughly the same provider cost again.

Paid services used: **one** data-access provider (Oxylabs or Zyte) + standard Azure resources. Nothing else.
