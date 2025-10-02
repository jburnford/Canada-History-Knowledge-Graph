#!/bin/bash
# Neo4j Deployment Script for Arbutus Cloud
# Run this on a fresh Ubuntu 22.04 VM

set -e

echo "======================================"
echo "Neo4j Canada Census - Arbutus Deploy"
echo "======================================"

# Configuration
NEO4J_PASSWORD=${1:-"changeme123"}
DATA_VOLUME="/dev/vdb"
BACKUP_VOLUME="/dev/vdc"

if [ "$NEO4J_PASSWORD" == "changeme123" ]; then
    echo "⚠️  WARNING: Using default password!"
    echo "Run with: ./deploy-neo4j.sh YOUR_SECURE_PASSWORD"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "Step 1: System Updates"
echo "----------------------"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo apt-get install -y wget curl gnupg software-properties-common

echo ""
echo "Step 2: Security Hardening"
echo "--------------------------"

# Install fail2ban
sudo apt-get install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Configure UFW (will be configured based on your network later)
sudo apt-get install -y ufw
echo "UFW installed - configure manually based on your network"

# Disable password authentication
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# Enable automatic security updates
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

echo ""
echo "Step 3: Format and Mount Volumes"
echo "---------------------------------"

# Check if volumes exist
if [ -b "$DATA_VOLUME" ]; then
    echo "Formatting data volume: $DATA_VOLUME"
    sudo mkfs.xfs -f -n ftype=1 $DATA_VOLUME
    sudo mkdir -p /var/lib/neo4j-data
    echo "$DATA_VOLUME /var/lib/neo4j-data xfs defaults,noatime 0 2" | sudo tee -a /etc/fstab
    sudo mount -a
    echo "✓ Data volume mounted at /var/lib/neo4j-data"
else
    echo "⚠️  Data volume $DATA_VOLUME not found - using local storage"
    sudo mkdir -p /var/lib/neo4j-data
fi

if [ -b "$BACKUP_VOLUME" ]; then
    echo "Formatting backup volume: $BACKUP_VOLUME"
    sudo mkfs.ext4 -F $BACKUP_VOLUME
    sudo mkdir -p /var/backups/neo4j
    echo "$BACKUP_VOLUME /var/backups/neo4j ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab
    sudo mount -a
    echo "✓ Backup volume mounted at /var/backups/neo4j"
else
    echo "⚠️  Backup volume $BACKUP_VOLUME not found - using local storage"
    sudo mkdir -p /var/backups/neo4j
fi

echo ""
echo "Step 4: Install Neo4j Community Edition"
echo "---------------------------------------"

# Add Neo4j repository
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list

# Install Neo4j
sudo apt-get update
sudo apt-get install -y neo4j

# Stop Neo4j (will configure first)
sudo systemctl stop neo4j

echo ""
echo "Step 5: Configure Neo4j"
echo "-----------------------"

# Set permissions
sudo chown -R neo4j:neo4j /var/lib/neo4j-data
sudo chown -R neo4j:neo4j /var/backups/neo4j

# Backup original config
sudo cp /etc/neo4j/neo4j.conf /etc/neo4j/neo4j.conf.original

# Configure Neo4j
sudo tee /etc/neo4j/neo4j.conf > /dev/null <<EOF
# Network
server.default_listen_address=0.0.0.0
server.bolt.listen_address=:7687
server.http.listen_address=:7474

# Database location (on data volume)
server.directories.data=/var/lib/neo4j-data/data
server.directories.logs=/var/lib/neo4j-data/logs
server.directories.import=/var/lib/neo4j-data/import
server.directories.plugins=/var/lib/neo4j-data/plugins

# Memory configuration (for 30GB RAM VM)
server.memory.heap.initial_size=8g
server.memory.heap.max_size=8g
server.memory.pagecache.size=16g

# Performance
dbms.memory.transaction.total.max=4g
db.tx_log.rotation.retention_policy=2 days

# Security
dbms.security.auth_enabled=true

# JVM tuning
server.jvm.additional=-XX:+UseG1GC
server.jvm.additional=-XX:+UnlockExperimentalVMOptions
server.jvm.additional=-XX:+TrustFinalNonStaticFields
server.jvm.additional=-XX:+DisableExplicitGC
EOF

echo "✓ Neo4j configured"

echo ""
echo "Step 6: System Tuning"
echo "---------------------"

# Disable Transparent Huge Pages (THP)
echo "Disabling THP..."
sudo tee /etc/systemd/system/disable-thp.service > /dev/null <<EOF
[Unit]
Description=Disable Transparent Huge Pages (THP)
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=neo4j.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never | tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null'
ExecStart=/bin/sh -c 'echo never | tee /sys/kernel/mm/transparent_hugepage/defrag > /dev/null'

[Install]
WantedBy=basic.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable disable-thp
sudo systemctl start disable-thp

# Adjust swappiness
echo "vm.swappiness = 1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Increase file descriptors
echo "neo4j soft nofile 60000" | sudo tee -a /etc/security/limits.conf
echo "neo4j hard nofile 60000" | sudo tee -a /etc/security/limits.conf

echo "✓ System tuned for Neo4j"

echo ""
echo "Step 7: Start Neo4j"
echo "-------------------"

sudo systemctl enable neo4j
sudo systemctl start neo4j

# Wait for Neo4j to start
echo "Waiting for Neo4j to start..."
for i in {1..30}; do
    if sudo systemctl is-active --quiet neo4j; then
        echo "✓ Neo4j started"
        break
    fi
    sleep 2
done

echo ""
echo "Step 8: Set Initial Password"
echo "-----------------------------"

# Wait for HTTP endpoint
sleep 10

# Set password
curl -X POST http://localhost:7474/user/neo4j/password \
  -u neo4j:neo4j \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"$NEO4J_PASSWORD\"}" 2>/dev/null && echo "✓ Password set" || echo "⚠️  Password may need manual setting"

echo ""
echo "======================================"
echo "✅ Neo4j Installation Complete!"
echo "======================================"
echo ""
echo "Next Steps:"
echo "1. Upload database dump: scp canada-census-20251002.dump ubuntu@VM:/tmp/"
echo "2. Restore database:"
echo "   sudo systemctl stop neo4j"
echo "   sudo cp /tmp/canada-census-20251002.dump /var/lib/neo4j-data/import/"
echo "   sudo chown neo4j:neo4j /var/lib/neo4j-data/import/canada-census-20251002.dump"
echo "   sudo -u neo4j neo4j-admin database load neo4j --from-path=/var/lib/neo4j-data/import"
echo "   sudo systemctl start neo4j"
echo ""
echo "3. Configure firewall (UFW):"
echo "   sudo ufw allow from YOUR_VPN_CIDR to any port 22"
echo "   sudo ufw allow from YOUR_VPN_CIDR to any port 7474"
echo "   sudo ufw allow from YOUR_VPN_CIDR to any port 7687"
echo "   sudo ufw enable"
echo ""
echo "4. Test connection:"
echo "   http://FLOATING_IP:7474 (Browser)"
echo "   bolt://FLOATING_IP:7687 (Bolt)"
echo ""
echo "Password: $NEO4J_PASSWORD"
echo ""
