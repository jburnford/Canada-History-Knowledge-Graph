# Neo4j VM Deployment on Arbutus (OpenStack)

This guide documents a repeatable, Docker-based deployment of Neo4j on the Arbutus cloud, including volumes, networking, and common troubleshooting for Error state instances.

## Overview

- OS: Ubuntu 24.04 LTS (Docker-based; 22.04 also fine)
- Deploy: Docker + Compose
- Data: Separate Cinder volume mounted at `/home/ubuntu/neo4j/data`
- Neo4j: Version 5.x with APOC + neosemantics (n10s)

## Prerequisites

- Quotas (example): 1 instance, 10 vCPUs, 32 GB RAM, 3 volumes, 3 snapshots, 1 TB storage, 1 Floating IP
- Security Group prepared to allow only from trusted IPs/VPN:
  - `22/tcp` (SSH), `7474/tcp` (Neo4j Browser), `7687/tcp` (Bolt)

## Launch VM

1) Instance
- Name: `neo4j-canada`
- Image: `Ubuntu-24.04-Noble-x64-2024-06`
- Flavor: `p8-16gb` (8 vCPU, 16 GB) or `p4-8gb` (4 vCPU, 8 GB)
- Availability Zone: `nova` (pick a specific AZ and reuse it for volumes)
- Network: select your project network (e.g., `def-jic823-dev-network`)
- Key Pair: create/import and select
- Security Group: allow only trusted sources for ports above

2) Optional User Data (cloud-init) – recommended (Option A: prepare only)

Paste this into the dashboard’s Customization Script (User Data):

```yaml
#cloud-config
package_update: true
packages: [docker.io, docker-compose-plugin]
write_files:
  - path: /home/ubuntu/neo4j/docker-compose.yml
    owner: ubuntu:ubuntu
    permissions: '0644'
    content: |
      version: "3.8"
      services:
        neo4j:
          image: neo4j:5
          container_name: neo4j
          restart: unless-stopped
          ports: ["7474:7474","7687:7687"]
          environment:
            - NEO4J_AUTH=neo4j/CHANGE_ME_STRONG_PASSWORD
            - NEO4J_PLUGINS=["apoc","n10s"]
            - NEO4J_server_memory_heap_initial__size=3G
            - NEO4J_server_memory_heap_max__size=3G
            - NEO4J_server_memory_pagecache_size=3G
            - NEO4J_dbms_security_procedures_allowlist=apoc.*,n10s.*
          volumes:
            - /home/ubuntu/neo4j/data:/data
            - /home/ubuntu/neo4j/logs:/logs
            - /home/ubuntu/neo4j/plugins:/plugins
            - /home/ubuntu/neo4j/import:/import
runcmd:
  - mkdir -p /home/ubuntu/neo4j/{data,logs,plugins,import}
  - chown -R ubuntu:ubuntu /home/ubuntu/neo4j
  - systemctl enable --now docker
```

This installs Docker/Compose, prepares directories, and writes `docker-compose.yml` but does not start Neo4j yet (avoids writing to root before the data volume is mounted).

## Create and Attach Data Volume

Dashboard → Volumes → Create Volume
- Name: `neo4j-data`
- Size: 200–300 GiB
- Availability Zone: `nova` (must match the instance)
- Source: No source (empty volume)

Attach the volume: Volumes → neo4j-data → Manage Attachments → Attach to `neo4j-canada`.

## Mount Volume on VM

SSH to the VM as `ubuntu` and run:

```bash
lsblk                             # find attached device (e.g., /dev/vdb)
sudo mkfs.ext4 -L neo4j-data /dev/vdb
UUID=$(sudo blkid -s UUID -o value /dev/vdb)
sudo mkdir -p /home/ubuntu/neo4j/data
echo "UUID=$UUID /home/ubuntu/neo4j/data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mount -a
sudo chown -R ubuntu:ubuntu /home/ubuntu/neo4j
df -h /home/ubuntu/neo4j/data     # verify mounted capacity
```

## Start Neo4j (Docker)

```bash
cd /home/ubuntu/neo4j
docker compose up -d
```

Allocate a Floating IP and associate it with the instance. Access Neo4j Browser at `http://<floating-ip>:7474`.

## Memory Sizing

- `p4-8gb`: heap 3G, pagecache 3G
- `p8-16gb`: heap 6G, pagecache 6–8G

Adjust the values in `docker-compose.yml` and restart: `docker compose up -d`.

## Importing Data

Copy CSVs to the VM:

```bash
scp -r neo4j_cidoc_crm neo4j_census_v2 ubuntu@<ip>:/home/ubuntu/neo4j/import/
```

In Neo4j Browser:
- Create constraints/indexes (see `neo4j_census_v2/README_IMPORT.md`)
- Load spatial nodes/relationships from `neo4j_cidoc_crm/`
- Load v2 nodes/relationships from `neo4j_census_v2/`
- Use `:auto USING PERIODIC COMMIT 10000` on large files

## Troubleshooting Instance "Error" State

If the instance shows `Error` shortly after launch:

- Check console log: Instance → Actions → View Log. Look for scheduling or cloud-init errors.
- AZ capacity: Try a smaller flavor (e.g., `p4-8gb`) or a different AZ (if available to your project). Keep instance and volume in the same AZ.
- Network selection: Ensure `def-jic823-dev-network` is attached; avoid IPv6-only unless you configured IPv6 SG rules.
- User Data syntax: If cloud-init fails, re-launch without User Data or with minimal YAML (the block above) and validate `/var/log/cloud-init.log` after boot.
- Quotas: Verify vCPU/RAM limits and that the flavor does not exceed your quotas.
- Image/Flavor compatibility: If `p8-16gb` fails, test `p4-8gb`. If Ubuntu 24.04 image has issues, try Ubuntu 22.04.
- Security Groups: Misconfigured SG does not cause Error state, but can block SSH after boot. Ensure rules allow your IP.

If still failing, capture the console log and raise a ticket; include AZ, flavor, image, and time of failure.

## Security Notes

- Restrict SG to trusted IPs/VPN only
- Change default Neo4j password immediately
- Nightly `neo4j-admin dump` to object storage; optionally use volume snapshots

## Related Docs

- Spatial import: `neo4j_cidoc_crm/README_CIDOC_CRM.md`
- v2 measurements import: `neo4j_census_v2/README_IMPORT.md`

