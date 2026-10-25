# C. Deployed Azure results (observed)

Azure Container Apps Job `wmscraper-job` (cron `0 6 * * 1,4`, parallelism 1) runs the versioned release ZIP from Blob
Storage with its managed identity; the provider key comes from Key Vault.
* Executions 9x94wac and n36f032: provider quota exhausted -> store not verified -> NOT published.
* Execution 8z2ew0n: resumed the same run id, verified store #100, canaries ok, published 704 records to Blob
  Storage (04-published-*). Source fingerprint in the logs: 29492665b766...
