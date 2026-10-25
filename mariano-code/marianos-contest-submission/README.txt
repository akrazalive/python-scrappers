MARIANO'S CONTEST - SUBMISSION FOLDER
=====================================

A) CONTEST ENTRY (Freelancer "Submit entry" form)
   Upload:        ENTRY-1-results-board.png
   Title:         Mariano's Scraper - Live Run 1,027 Records, Store 53100544 Verified
   Description:   copy from ENTRY-1-description.txt (944 characters)
   AI use:        AI assisted
   Licensed:      This entry is entirely my own
   Sell price:    700
   Sealed:        ON (if available, so competitors cannot see it)

B) PRIVATE MESSAGE TO THE CONTEST HOLDER (never the public clarification board)
   Text:          send-to-client/MESSAGE-TO-CLIENT.txt
   Attach:        everything else in send-to-client/ (2.1 MB total)

C) BEFORE THE OBSERVED ACCEPTANCE RUN
   The Oxylabs trial quota is used up (both the Walmart and the Mariano's scrapers share the same key).
   Renew or upgrade the plan, then:
     cd D:\PROJECTS\Monthly-Test\marianos-scraper
     set PYTHONPATH=src
     python -m mscraper run --location marianos-544-crystal-lake --run 20261021T044142Z-cf40b8   (finishes the query-expansion run)
     python -m mscraper run --location marianos-544-crystal-lake                                 (full production run, all CSV rows)
