# Neo4j Deployment on Arbutus Cloud

## Project Resources (Approved)
- **VCPUs**: 10
- **RAM**: 32GB
- **Instances**: 1
- **Storage**: 1000GB volume
- **Object Storage**: 500GB (for backups)
- **CephFS**: 200GB (shared filesystem)
- **Floating IPs**: 1

## Architecture Overview

```
Internet → Floating IP → Neo4j VM → Volume Storage
                              ↓
                         Object Storage (Backups)
```

### VM Specifications
- **OS**: Ubuntu 22.04 LTS
- **Flavor**: c8-30gb-186 (8 vCPUs, 30GB RAM) or similar
- **Primary Volume**: 100GB (OS + Neo4j binaries)
- **Data Volume**: 500GB (Neo4j database)
- **Backup Volume**: 200GB (local backup staging)

### Network Configuration
- **Floating IP**: Public access (VPN/office only)
- **Security Group**:
  - Port 22 (SSH): VPN/office CIDR only
  - Port 7474 (HTTP): VPN/office CIDR only
  - Port 7687 (Bolt): VPN/office CIDR only
  - All other ports: DENY

## Deployment Steps

### 1. Create VM Instance

```bash
# Via OpenStack CLI or Arbutus Dashboard
openstack server create \
  --flavor c8-30gb-186 \
  --image "Ubuntu 22.04" \
  --key-name your-ssh-key \
  --network def-jic823-network \
  --security-group neo4j-sg \
  --boot-from-volume 100 \
  neo4j-canada-census
```

### 2. Create and Attach Volumes

```bash
# Data volume
openstack volume create --size 500 neo4j-data
openstack server add volume neo4j-canada-census neo4j-data

# Backup staging volume
openstack volume create --size 200 neo4j-backups
openstack server add volume neo4j-canada-census neo4j-backups
```

### 3. Assign Floating IP

```bash
openstack floating ip create public
openstack server add floating ip neo4j-canada-census <FLOATING-IP>
```

## Security Configuration

### SSH Hardening
```bash
# Disable password authentication
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# Install fail2ban
sudo apt-get update && sudo apt-get install -y fail2ban
sudo systemctl enable fail2ban
```

### Firewall (UFW)
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <VPN-CIDR> to any port 22
sudo ufw allow from <OFFICE-CIDR> to any port 22
sudo ufw allow from <VPN-CIDR> to any port 7474
sudo ufw allow from <VPN-CIDR> to any port 7687
sudo ufw enable
```

### Automatic Updates
```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

## Neo4j Installation

### Install Neo4j Community Edition

```bash
# Add Neo4j repository
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list

# Install Neo4j
sudo apt-get update
sudo apt-get install -y neo4j

# Stop Neo4j (we'll configure first)
sudo systemctl stop neo4j
```

### Volume Setup

```bash
# Format data volume
sudo mkfs.xfs -n ftype=1 /dev/vdb
sudo mkdir -p /var/lib/neo4j-data

# Format backup volume
sudo mkfs.ext4 /dev/vdc
sudo mkdir -p /var/backups/neo4j

# Add to /etc/fstab
echo "/dev/vdb /var/lib/neo4j-data xfs defaults,noatime 0 2" | sudo tee -a /etc/fstab
echo "/dev/vdc /var/backups/neo4j ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab

# Mount volumes
sudo mount -a

# Set permissions
sudo chown -R neo4j:neo4j /var/lib/neo4j-data
sudo chown -R neo4j:neo4j /var/backups/neo4j
```

### Neo4j Configuration

Edit `/etc/neo4j/neo4j.conf`:

```conf
# Network
server.default_listen_address=0.0.0.0
server.bolt.listen_address=:7687
server.http.listen_address=:7474

# Database location (on data volume)
server.directories.data=/var/lib/neo4j-data/data
server.directories.logs=/var/lib/neo4j-data/logs
server.directories.import=/var/lib/neo4j-data/import

# Memory (for 30GB RAM VM)
server.memory.heap.initial_size=8g
server.memory.heap.max_size=8g
server.memory.pagecache.size=16g

# Performance
dbms.memory.transaction.total.max=4g
db.tx_log.rotation.retention_policy=2 days

# Security
dbms.security.auth_enabled=true
```

### Restore Database

```bash
# Copy dump file to VM (from local machine)
scp canada-census-20251002.dump ubuntu@<FLOATING-IP>:/tmp/

# On VM: Copy to import directory
sudo cp /tmp/canada-census-20251002.dump /var/lib/neo4j-data/import/
sudo chown neo4j:neo4j /var/lib/neo4j-data/import/canada-census-20251002.dump

# Restore database
sudo -u neo4j neo4j-admin database load neo4j --from-path=/var/lib/neo4j-data/import

# Start Neo4j
sudo systemctl enable neo4j
sudo systemctl start neo4j

# Set initial password
curl -X POST http://localhost:7474/user/neo4j/password \
  -u neo4j:neo4j \
  -H "Content-Type: application/json" \
  -d '{"password":"<NEW-SECURE-PASSWORD>"}'
```

## Backup Strategy

### Nightly Backups to Object Storage

Create `/usr/local/bin/neo4j-backup.sh`:

```bash
#!/bin/bash
set -e

DATE=$(date +%Y%m%d)
BACKUP_DIR="/var/backups/neo4j"
DUMP_FILE="$BACKUP_DIR/neo4j-$DATE.dump"
S3_BUCKET="s3://neo4j-backups-jic823"

# Stop Neo4j
sudo systemctl stop neo4j

# Create dump
sudo -u neo4j neo4j-admin database dump neo4j --to-path=$BACKUP_DIR

# Rename with date
sudo mv $BACKUP_DIR/neo4j.dump $DUMP_FILE

# Upload to object storage (using swift CLI)
swift upload neo4j-backups neo4j-$DATE.dump --object-name=neo4j-$DATE.dump

# Start Neo4j
sudo systemctl start neo4j

# Cleanup old local backups (keep 7 days)
find $BACKUP_DIR -name "neo4j-*.dump" -mtime +7 -delete

echo "Backup completed: $DUMP_FILE -> $S3_BUCKET"
```

Add to crontab:
```bash
sudo crontab -e
# Add:
0 2 * * * /usr/local/bin/neo4j-backup.sh >> /var/log/neo4j-backup.log 2>&1
```

### Weekly Volume Snapshots

```bash
# Via OpenStack CLI
openstack volume snapshot create --volume neo4j-data neo4j-data-snapshot-$(date +%Y%m%d)
```

Add to crontab (run from local machine or a management VM):
```bash
0 3 * * 0 /usr/local/bin/create-volume-snapshot.sh
```

### Quarterly Restore Tests

Create `/usr/local/bin/test-restore.sh`:

```bash
#!/bin/bash
# Test restore from latest backup
# Run on a separate test VM quarterly
```

## Monitoring

### System Monitoring

```bash
# Install monitoring tools
sudo apt-get install -y prometheus-node-exporter

# Neo4j metrics (exposed on port 2004)
# Add to prometheus scrape config
```

### Log Monitoring

```bash
# Monitor authentication failures
sudo tail -f /var/log/auth.log | grep -i "failed\|invalid"

# Monitor Neo4j logs
sudo tail -f /var/lib/neo4j-data/logs/neo4j.log

# fail2ban status
sudo fail2ban-client status sshd
```

### Alerts (Optional)

- Disk usage > 80%
- Heap memory > 90%
- Page cache < 50%
- Query latency > 1s average
- Failed authentication attempts > 10/hour

## Access for Team Members

### Option 1: VPN Access (Recommended)
- Set up OpenVPN or WireGuard on Arbutus
- Team members connect via VPN
- Direct access to Neo4j

### Option 2: SSH Tunneling
```bash
# Team member creates SSH tunnel
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 ubuntu@<FLOATING-IP>

# Access Neo4j Browser at http://localhost:7474
```

### Option 3: Nginx Reverse Proxy with TLS
```bash
# Install nginx and certbot
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Configure nginx for Neo4j
# Add basic auth for additional security
```

## Maintenance Schedule

**Daily**:
- Automated backups (2 AM)
- Log rotation

**Weekly**:
- Volume snapshots (Sunday 3 AM)
- Security updates (automatic)

**Monthly**:
- Full system update
- Review logs and metrics
- Disk cleanup

**Quarterly**:
- Restore test from backup
- Security audit
- Password rotation

## Cost Estimate

Based on Compute Canada pricing (free for research):
- **Compute**: Free (research allocation)
- **Storage**: Free (within allocation)
- **Object Storage**: Free (within 500GB allocation)
- **Bandwidth**: Unlimited within Canada

**Actual cost**: $0 (covered by Digital Research Alliance grant)

## Disaster Recovery

**RTO** (Recovery Time Objective): 2 hours
**RPO** (Recovery Point Objective): 24 hours (daily backups)

### Recovery Steps:
1. Create new VM from image
2. Attach data volume OR create new volume from snapshot
3. Restore latest database dump from object storage
4. Update DNS/floating IP
5. Verify data integrity

## Support Contacts

- **Alliance Support**: support@tech.alliancecan.ca
- **Ticket System**: https://support.alliancecan.ca/otrs/customer.pl
- **Documentation**: https://docs.alliancecan.ca/wiki/Cloud

---

**Last Updated**: October 2, 2025
**Database Size**: 283MB (compressed dump), ~2.2GB (uncompressed)
**Records**: 1.4M nodes, 4.5M relationships
