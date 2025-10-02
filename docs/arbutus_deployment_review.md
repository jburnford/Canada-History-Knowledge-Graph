# Arbutus Deployment and Data Review

## Overview
This document captures a review of the Arbutus cloud migration plan, deployment scripts, and backup automation, along with a check on the delivered 1911 and 1921 census data slices.

## Quick Start Plan
* The provisioning checklist in `arbutus/QUICK_START.md` is clear about compute shape, attached volumes, and firewall rules, and it walks through deployment, restore, and verification steps in a logical order.【F:arbutus/QUICK_START.md†L1-L161】
* The verification step assumes that counting 1921 presences will return 5,585 nodes (5,363 CSD + 222 CD). The staged CSVs hold 5,363 CSD presences (5,364 rows including the header) and 222 CD presences (223 rows with header), so the target value is consistent with the data dump.【F:arbutus/QUICK_START.md†L124-L139】【be952e†L1-L2】【0b130c†L1-L2】
* The guide does not yet describe how to validate that swap is disabled, that automatic security updates completed, or that the monitoring cron jobs are in place—items worth adding to the post-install checklist.

## Deployment Script Review (`deploy-neo4j.sh`)
* The script hardens SSH access, formats and mounts the dedicated data/backup volumes, and rewrites `neo4j.conf` to use those mounts and production-ready memory settings.【F:arbutus/deploy-neo4j.sh†L11-L140】 This aligns with the hardware described in the plan.
* `dpkg-reconfigure -plow unattended-upgrades` is interactive on Ubuntu unless `DEBIAN_FRONTEND=noninteractive` is set; running it inside an automated script risks hanging the deployment. Consider replacing it with a non-interactive configuration snippet or pre-seeding debconf.【F:arbutus/deploy-neo4j.sh†L51-L53】
* The repository setup still uses `apt-key`, which is deprecated on modern Debian/Ubuntu. Switching to `gpg --dearmor` and dropping the key into `/usr/share/keyrings` would future-proof the install.【F:arbutus/deploy-neo4j.sh†L88-L90】
* After the first start the script uses the HTTP API to set the password.【F:arbutus/deploy-neo4j.sh†L197-L208】 In Neo4j 5+, the recommended approach is `neo4j-admin dbms set-initial-password`; even on 4.4 this call can fail if the service takes longer than ten seconds to become ready. Adding a readiness loop or using the admin CLI would make the step more reliable.
* The “restore database” instructions echo the older `neo4j-admin database load` syntax but omit the `--force` flag required when the `neo4j` database already exists. Expect to delete the default store (`/var/lib/neo4j-data/data/databases/neo4j`) or add `--overwrite-destination` when restoring on top of an existing deployment.【F:arbutus/deploy-neo4j.sh†L215-L223】

## Backup and Monitoring Script Review (`setup-backups.sh`)
* The script provisions daily offline dumps, optional Swift uploads, a quarterly restore test, and lightweight health checks—good coverage for basic operations.【F:arbutus/setup-backups.sh†L11-L283】
* `swift upload neo4j-backups $(basename $DUMP_FILE)` drops the path, so uploads will fail unless the working directory is `/var/backups/neo4j`. Use the absolute path (`swift upload neo4j-backups "$DUMP_FILE" ...`) or `cd` before uploading.【F:arbutus/setup-backups.sh†L61-L67】
* The backup job stops Neo4j each night. That guarantees consistency but introduces daily downtime; enabling the Neo4j Enterprise online backup or using filesystem snapshots could reduce disruption if licensing allows.【F:arbutus/setup-backups.sh†L41-L66】
* Monitoring depends on `jstat`, `bc`, and `mail`, none of which are installed in the script. Either install them or guard the checks so they degrade gracefully.【F:arbutus/setup-backups.sh†L231-L249】
* The quarterly restore cron entry inlines `date` arithmetic. Cron already enforces the schedule with the day-of-week field, so the additional shell test may be redundant and adds quoting complexity for `%` escaping.【F:arbutus/setup-backups.sh†L213-L216】

## 1911 & 1921 Data Review
* The completion report documents that observations (measurements) are only loaded through 1901; 1911 and 1921 numeric facts remain outstanding, so analytics on those years will only surface spatial/topological information for now.【F:NEO4J_DATABASE_COMPLETE.md†L72-L76】【F:NEO4J_DATABASE_COMPLETE.md†L148-L152】
* The staged CSVs provide 3,589 1911 CSD presences (3,590 rows including the header) and 5,363 1921 CSD presences (5,364 rows including the header), along with full CD coverage for both years.【e18454†L1-L2】【3b1b73†L1-L6】【be952e†L1-L2】【175ecc†L1-L6】【0b130c†L1-L2】【c3230d†L1-L6】 This means 1911 geography is materially thinner than 1921—likely due to the outstanding multi-layer GDB work flagged elsewhere.
* The ambiguous mapping report between 1911 and 1921 highlights numerous low-overlap cases (e.g., Alberta L.I.D. districts) that will need curatorial decisions before reliable temporal aggregation is possible.【F:year_links_output/ambiguous_1911_1921.csv†L1-L19】
* 1911 ingestion plans exist (`docs/canada_kg_plan.md`), but until those parsers run and measurements load, downstream users should be warned that 1911/1921 contain geometry and topology only.【F:docs/canada_kg_plan.md†L1-L115】 Consider surfacing this caveat in the Quick Start checklist and any user-facing documentation.

## Recommendations
1. Tweak the automation scripts as noted above (non-interactive unattended-upgrades, modern key import, robust password initialization, and absolute Swift upload paths).
2. Extend the Quick Start checklist with security/monitoring validation steps and explicitly call out the limited 1911/1921 measurement coverage.
3. Prioritize the outstanding 1911/1921 measurement ingestion to balance spatial and numeric coverage, and resolve ambiguous overlaps before enabling longitudinal rollups.
