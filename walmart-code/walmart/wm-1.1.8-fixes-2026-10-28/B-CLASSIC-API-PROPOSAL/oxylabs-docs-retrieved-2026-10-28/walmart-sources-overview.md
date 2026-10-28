> For the complete documentation index, see [llms.txt](https://developers.oxylabs.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://developers.oxylabs.io/products/web-scraper-api/targets/e-commerce/walmart.md).

# Walmart

Learn how to use the Walmart scraper.

With Web Scraper API, you can scrape various types of **Walmart** pages; below is an overview of all supported scrapers and their respective `source` values. Both sources have a dedicated parser: add `"parse": true` to receive structured JSON instead of the page HTML. Each source is described on its own page, linked below.

{% hint style="warning" %}
For some targets our system **forces JavaScript rendering** even if you do not set `render`; those requests count as rendered traffic. The list of force-rendered targets and how to switch rendering off are in [Forcing rendering on specific pages](/products/web-scraper-api/features/js-rendering-and-browser-control.md#forcing-rendering-on-specific-pages).
{% endhint %}

<table><thead><tr><th width="250">Source</th><th>Description</th></tr></thead><tbody><tr><td><code>walmart_search</code></td><td><a href="/products/web-scraper-api/targets/e-commerce/walmart/search.md"><strong>Search page</strong></a> for a search term of your choice.</td></tr><tr><td><code>walmart_product</code></td><td><a href="/products/web-scraper-api/targets/e-commerce/walmart/product.md"><strong>Product page</strong></a> of a product ID of your choice.</td></tr></tbody></table>

Any other Walmart page can be scraped by passing its `url` alone, no `source` needed.

{% hint style="info" %}
Besides the parameters listed on the source pages, you can include additional parameters such as `user_agent_type`, `geo_location`, `render`, and more to customize your scraping request. Read more [here](/products/web-scraper-api/features.md).
{% endhint %}


---

# Agent Instructions
This documentation is published with GitBook. GitBook is the documentation platform designed so that both humans and AI agents can read, navigate, and reason over technical content effectively. Learn more at gitbook.com.

## Querying This Documentation
If you need additional information that is not directly available in this page, you can query the documentation by asking a question.

Perform an HTTP GET request on the following URL with the `ask` and `goal` query parameters:

```
GET https://developers.oxylabs.io/products/web-scraper-api/targets/e-commerce/walmart.md?ask=<question>&goal=<user_goal>
```

`ask` is the immediate question: it should be specific, self-contained, and written in natural language.
`goal` is what the user is ultimately trying to achieve, the reason they need the answer. Sharing it helps GitBook give you a better, more relevant answer. A goal is most helpful when it describes the outcome the user wants rather than restating the question. For example, with `ask=how do I create an API token`, a goal like `automate deployments from our CI pipeline` lets GitBook tailor the answer to that use case.

The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
