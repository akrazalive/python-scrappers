# E. Production traversal - live findings

Live discovery of the full Balloons category at store #100 with production settings (no demonstration caps).

Findings from the source responses:
* Without a pickup/availability facet (required so unavailable products are kept), Walmart's store-scoped listings
  include its whole online catalog. Example: "Balloons by Color" reports 24,201 products.
* Subcategory splitting and whole-dollar price partitioning work (02-partition-plan-from-live-probes.csv:
  every probed band with Walmart's own count).
* Walmart applies price filters at whole-dollar resolution only. Some $1 bands still exceed the 25-page window
  (>1,000 products), so price partitioning alone cannot exhaust them.

The full page crawl was stopped deliberately: completing it for one category of the online catalog needs 1,000+
pages, i.e. hours and provider cost. The production scope decision (store assortment vs whole online catalog) is
raised with the client; additional partitioning dimensions (sort order, brand) are proposed for $1 bands.
