# Arbutus Cloud Deployment - Quick Start

## Prerequisites

- ✅ Arbutus cloud account (jic823)
- ✅ SSH key pair created and added to Arbutus
- ✅ Database dump ready: `canada-census-20251002.dump` (283MB)

## Step-by-Step Deployment

### 1. Create VM on Arbutus Dashboard

https://arbutus.cloud.computecanada.ca/

**Instance Details:**
- Name: `neo4j-canada-census`
- Flavor: `c8-30gb-186` (8 vCPUs, 30GB RAM)
- Image: `Ubuntu-22.04-Jammy-x64-2024-09` (or latest Ubuntu 22.04)
- Key Pair: Select your SSH key (`jic823-usask`)
- Network: `def-jic823-network`

**Storage:**
- Boot Volume: 100GB
- Create 2 additional volumes:
  - `neo4j-data`: 500GB (attach to `/dev/vdb`)
  - `neo4j-backups`: 200GB (attach to `/dev/vdc`)

**Security Groups:**
Create `neo4j-sg`:
```
Ingress Rules:
- Port 22 (SSH): YOUR_IP/32 or VPN_CIDR
- Port 7474 (HTTP): YOUR_IP/32 or VPN_CIDR
- Port 7687 (Bolt): YOUR_IP/32 or VPN_CIDR

Egress Rules:
- All traffic: 0.0.0.0/0 (for updates)
```

**Floating IP:**
- Create and assign a floating IP to the instance

### 2. Initial Connection

```bash
# Get floating IP from Arbutus dashboard
FLOATING_IP="<YOUR-FLOATING-IP>"

# Connect via SSH
ssh ubuntu@$FLOATING_IP

# Verify volumes are attached
lsblk
# Should see vdb (500GB) and vdc (200GB)
```

### 3. Deploy Neo4j

```bash
# On the VM:

# Copy deployment script
wget https://raw.githubusercontent.com/jburnford/Canada-History-Knowledge-Graph/main/arbutus/deploy-neo4j.sh

# Make executable
chmod +x deploy-neo4j.sh

# Run deployment (use a STRONG password)
./deploy-neo4j.sh YOUR_SECURE_PASSWORD

# Wait for deployment to complete (~10 minutes)
```

### 4. Upload and Restore Database

**From your local machine (WSL):**

```bash
# Upload database dump
scp canada-census-20251002.dump ubuntu@$FLOATING_IP:/tmp/

# SSH to VM
ssh ubuntu@$FLOATING_IP

# Restore database
sudo systemctl stop neo4j
sudo cp /tmp/canada-census-20251002.dump /var/lib/neo4j-data/import/
sudo chown neo4j:neo4j /var/lib/neo4j-data/import/canada-census-20251002.dump
sudo -u neo4j neo4j-admin database load neo4j --from-path=/var/lib/neo4j-data/import
sudo systemctl start neo4j

# Verify Neo4j is running
sudo systemctl status neo4j

# Check logs
sudo tail -f /var/lib/neo4j-data/logs/neo4j.log
```

### 5. Configure Firewall

**On the VM:**

```bash
# Get your IP
MY_IP=$(curl -s https://api.ipify.org)

# Configure UFW
sudo ufw allow from $MY_IP/32 to any port 22
sudo ufw allow from $MY_IP/32 to any port 7474
sudo ufw allow from $MY_IP/32 to any port 7687
sudo ufw enable

# Verify rules
sudo ufw status
```

### 6. Test Connection

**From your browser:**
```
http://<FLOATING-IP>:7474
```

**Connection Details:**
- URL: `bolt://<FLOATING-IP>:7687`
- Username: `neo4j`
- Password: `YOUR_SECURE_PASSWORD`

**Test query:**
```cypher
// Count all nodes
MATCH (n) RETURN count(n);
// Should return ~1.4M nodes

// Check 1921 data
MATCH (p:E93_Presence {census_year: 1921})
RETURN count(p);
// Should return 5,585 (5,363 CSDs + 222 CDs)
```

### 7. Setup Backups

```bash
# On the VM:

# Copy backup script
wget https://raw.githubusercontent.com/jburnford/Canada-History-Knowledge-Graph/main/arbutus/setup-backups.sh

chmod +x setup-backups.sh
./setup-backups.sh

# Configure Swift for object storage
# (Download OpenStack RC file from Arbutus dashboard first)
source ~/project-openrc.sh
swift post neo4j-backups

# Test manual backup
sudo /usr/local/bin/neo4j-backup.sh

# Verify backup
swift list neo4j-backups
```

### 8. Add Team Members

**For each team member:**

1. They generate SSH key: `ssh-keygen -t ed25519`
2. They send you their public key
3. You add to VM:
```bash
ssh ubuntu@$FLOATING_IP
echo "ssh-ed25519 AAAA... team.member@email.com" >> ~/.ssh/authorized_keys
```

### 9. Setup SSH Config (Optional)

**On your local machine:**

Edit `~/.ssh/config`:
```
Host neo4j-arbutus
    HostName <FLOATING-IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60

Host neo4j-tunnel
    HostName <FLOATING-IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    LocalForward 7474 localhost:7474
    LocalForward 7687 localhost:7687
```

Connect via tunnel:
```bash
ssh -N neo4j-tunnel &
# Access Neo4j at http://localhost:7474
```

## Maintenance Schedule

- **Daily**: Automated backups (2 AM)
- **Weekly**: Volume snapshots (manual setup)
- **Monthly**: System updates
- **Quarterly**: Restore tests

## Monitoring

**Check service status:**
```bash
sudo systemctl status neo4j
sudo journalctl -u neo4j -f
```

**Check disk usage:**
```bash
df -h /var/lib/neo4j-data
```

**Check backups:**
```bash
ls -lh /var/backups/neo4j/
swift list neo4j-backups
```

**Check logs:**
```bash
tail -f /var/log/neo4j-backup.log
tail -f /var/lib/neo4j-data/logs/neo4j.log
```

## Troubleshooting

### Can't connect to Neo4j
```bash
# Check if running
sudo systemctl status neo4j

# Check firewall
sudo ufw status

# Check logs
sudo journalctl -u neo4j -n 50
```

### Out of memory
```bash
# Check heap usage
jstat -gc $(pgrep -f neo4j)

# Restart Neo4j
sudo systemctl restart neo4j
```

### Disk full
```bash
# Check usage
df -h

# Clean old backups
find /var/backups/neo4j -name "neo4j-*.dump.gz" -mtime +7 -delete
```

## Cost Tracking

All resources are free within your allocation:
- 10 vCPUs: Using 8 ✓
- 32GB RAM: Using 30GB ✓
- 1000GB storage: Using 800GB ✓
- 500GB object storage: TBD (backups)

Check usage:
```bash
openstack limits show --absolute
```

## Support

- **Alliance Documentation**: https://docs.alliancecan.ca/wiki/Cloud
- **Ticket System**: https://support.alliancecan.ca/otrs/customer.pl
- **Email**: support@tech.alliancecan.ca

---

**Deployment Checklist:**
- [ ] VM created with correct flavor
- [ ] Volumes attached (data + backups)
- [ ] Floating IP assigned
- [ ] SSH access working
- [ ] Neo4j deployed
- [ ] Database restored
- [ ] Firewall configured
- [ ] Backups configured
- [ ] Team access granted
- [ ] Monitoring setup
- [ ] Documentation updated

**Database Stats:**
- Nodes: 1,400,000
- Relationships: 4,500,000
- Dump size: 283MB (compressed)
- Memory footprint: ~24GB (heap + page cache)
