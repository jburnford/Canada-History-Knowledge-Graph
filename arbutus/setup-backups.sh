#!/bin/bash
# Setup automated backups for Neo4j on Arbutus
# Run this after Neo4j is deployed and running

set -e

echo "========================================="
echo "Neo4j Backup Configuration"
echo "========================================="

# Configuration
SWIFT_CONTAINER="neo4j-backups"
BACKUP_DIR="/var/backups/neo4j"

echo ""
echo "Step 1: Install Swift Client for Object Storage"
echo "------------------------------------------------"

sudo apt-get update
sudo apt-get install -y python3-swiftclient python3-keystoneclient

echo "✓ Swift client installed"

echo ""
echo "Step 2: Create Backup Script"
echo "----------------------------"

sudo tee /usr/local/bin/neo4j-backup.sh > /dev/null <<'EOF'
#!/bin/bash
# Automated Neo4j backup to Object Storage

set -e

DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/var/backups/neo4j"
DUMP_FILE="$BACKUP_DIR/neo4j-$DATE.dump"
LOG_FILE="/var/log/neo4j-backup.log"

echo "$(date): Starting backup..." >> $LOG_FILE

# Stop Neo4j
echo "$(date): Stopping Neo4j..." >> $LOG_FILE
sudo systemctl stop neo4j

# Create dump
echo "$(date): Creating dump..." >> $LOG_FILE
sudo -u neo4j neo4j-admin database dump neo4j --to-path=$BACKUP_DIR

# Rename with timestamp
sudo mv $BACKUP_DIR/neo4j.dump $DUMP_FILE

# Compress (optional - saves storage)
echo "$(date): Compressing..." >> $LOG_FILE
gzip $DUMP_FILE
DUMP_FILE="$DUMP_FILE.gz"

# Start Neo4j
echo "$(date): Starting Neo4j..." >> $LOG_FILE
sudo systemctl start neo4j

# Upload to object storage
if command -v swift &> /dev/null; then
    echo "$(date): Uploading to object storage..." >> $LOG_FILE
    swift upload neo4j-backups $(basename $DUMP_FILE) --object-name=neo4j-$DATE.dump.gz 2>&1 >> $LOG_FILE
    echo "$(date): Upload complete" >> $LOG_FILE
else
    echo "$(date): Swift not configured - backup kept locally only" >> $LOG_FILE
fi

# Cleanup old local backups (keep 7 days)
find $BACKUP_DIR -name "neo4j-*.dump.gz" -mtime +7 -delete

echo "$(date): Backup completed: $DUMP_FILE" >> $LOG_FILE

# Send email notification (optional)
if command -v mail &> /dev/null; then
    echo "Neo4j backup completed: neo4j-$DATE.dump.gz" | mail -s "Neo4j Backup Success" jim.clifford@usask.ca
fi
EOF

sudo chmod +x /usr/local/bin/neo4j-backup.sh
echo "✓ Backup script created: /usr/local/bin/neo4j-backup.sh"

echo ""
echo "Step 3: Setup Cron Job"
echo "----------------------"

# Add to crontab (runs daily at 2 AM)
(sudo crontab -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/neo4j-backup.sh") | sudo crontab -

echo "✓ Cron job configured (daily at 2 AM)"

echo ""
echo "Step 4: Create Swift Configuration"
echo "-----------------------------------"

echo "To configure Swift for object storage:"
echo ""
echo "1. Download OpenStack RC file from Arbutus dashboard:"
echo "   Project → API Access → Download OpenStack RC File v3"
echo ""
echo "2. Source the RC file:"
echo "   source ~/project-openrc.sh"
echo "   # Enter your password when prompted"
echo ""
echo "3. Create Swift container:"
echo "   swift post $SWIFT_CONTAINER"
echo ""
echo "4. Test Swift access:"
echo "   swift list"
echo ""
echo "5. Add credentials to .bashrc for cron:"
echo "   cat ~/project-openrc.sh >> ~/.bashrc"
echo ""

echo ""
echo "Step 5: Create Volume Snapshot Script"
echo "--------------------------------------"

sudo tee /usr/local/bin/create-volume-snapshot.sh > /dev/null <<'EOF'
#!/bin/bash
# Create weekly volume snapshots (run from local machine or management VM)

DATE=$(date +%Y%m%d)
DATA_VOLUME="neo4j-data"
BACKUP_VOLUME="neo4j-backups"

# Create snapshots
openstack volume snapshot create \
  --volume $DATA_VOLUME \
  --force \
  "$DATA_VOLUME-snapshot-$DATE"

openstack volume snapshot create \
  --volume $BACKUP_VOLUME \
  --force \
  "$BACKUP_VOLUME-snapshot-$DATE"

# Cleanup old snapshots (keep 4 weeks)
# List snapshots older than 28 days and delete
openstack volume snapshot list --long -f value | \
  awk -v date=$(date -d '28 days ago' +%Y-%m-%d) '$5 < date {print $1}' | \
  xargs -r -I {} openstack volume snapshot delete {}

echo "Snapshots created: $DATA_VOLUME-snapshot-$DATE, $BACKUP_VOLUME-snapshot-$DATE"
EOF

sudo chmod +x /usr/local/bin/create-volume-snapshot.sh
echo "✓ Snapshot script created (run from machine with OpenStack CLI)"

echo ""
echo "Step 6: Create Restore Test Script"
echo "-----------------------------------"

sudo tee /usr/local/bin/test-restore.sh > /dev/null <<'EOF'
#!/bin/bash
# Test database restore (run quarterly)

set -e

BACKUP_DIR="/var/backups/neo4j"
TEST_DB_DIR="/tmp/neo4j-restore-test"

echo "Finding latest backup..."
LATEST_BACKUP=$(ls -t $BACKUP_DIR/neo4j-*.dump.gz 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "❌ No backup found in $BACKUP_DIR"
    exit 1
fi

echo "Testing restore of: $LATEST_BACKUP"

# Decompress if needed
if [[ $LATEST_BACKUP == *.gz ]]; then
    gunzip -c $LATEST_BACKUP > /tmp/neo4j-test.dump
    TEST_DUMP="/tmp/neo4j-test.dump"
else
    TEST_DUMP=$LATEST_BACKUP
fi

# Create test directory
rm -rf $TEST_DB_DIR
mkdir -p $TEST_DB_DIR

# Attempt restore
echo "Restoring to test directory..."
sudo -u neo4j neo4j-admin database load test-db --from-path=/tmp

if [ $? -eq 0 ]; then
    echo "✅ Restore test PASSED"
    echo "Backup is valid: $LATEST_BACKUP"

    # Cleanup
    rm -f /tmp/neo4j-test.dump

    # Send success notification
    echo "Restore test passed for $LATEST_BACKUP" | mail -s "Neo4j Restore Test: SUCCESS" jim.clifford@usask.ca
    exit 0
else
    echo "❌ Restore test FAILED"
    echo "Backup may be corrupt: $LATEST_BACKUP"

    # Send failure notification
    echo "Restore test FAILED for $LATEST_BACKUP" | mail -s "Neo4j Restore Test: FAILED" jim.clifford@usask.ca
    exit 1
fi
EOF

sudo chmod +x /usr/local/bin/test-restore.sh
echo "✓ Restore test script created"

# Add quarterly restore test to cron (1st Sunday of quarter)
(sudo crontab -l 2>/dev/null; echo "0 3 1 1,4,7,10 0 [ \$(date +\\%u) -eq 7 ] && /usr/local/bin/test-restore.sh") | sudo crontab -

echo ""
echo "Step 7: Setup Monitoring"
echo "------------------------"

sudo tee /usr/local/bin/check-neo4j-health.sh > /dev/null <<'EOF'
#!/bin/bash
# Monitor Neo4j health metrics

# Check if Neo4j is running
if ! systemctl is-active --quiet neo4j; then
    echo "CRITICAL: Neo4j is not running"
    systemctl restart neo4j
    echo "Neo4j was down and has been restarted" | mail -s "Neo4j ALERT: Service Down" jim.clifford@usask.ca
fi

# Check disk usage
DISK_USAGE=$(df -h /var/lib/neo4j-data | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "WARNING: Disk usage at ${DISK_USAGE}%"
    echo "Disk usage critical: ${DISK_USAGE}%" | mail -s "Neo4j ALERT: Disk Space" jim.clifford@usask.ca
fi

# Check memory
HEAP_USAGE=$(jstat -gc $(pgrep -f neo4j) | tail -1 | awk '{print ($3+$4+$6+$8)/($3+$4+$5+$6+$7+$8)*100}')
if (( $(echo "$HEAP_USAGE > 90" | bc -l) )); then
    echo "WARNING: Heap usage at ${HEAP_USAGE}%"
    echo "Heap memory critical: ${HEAP_USAGE}%" | mail -s "Neo4j ALERT: Memory" jim.clifford@usask.ca
fi

# Check failed login attempts
FAILED_LOGINS=$(grep "Failed authentication" /var/lib/neo4j-data/logs/neo4j.log | grep -c "$(date +%Y-%m-%d)" || true)
if [ $FAILED_LOGINS -gt 10 ]; then
    echo "WARNING: $FAILED_LOGINS failed login attempts today"
    echo "$FAILED_LOGINS failed authentication attempts" | mail -s "Neo4j ALERT: Security" jim.clifford@usask.ca
fi
EOF

sudo chmod +x /usr/local/bin/check-neo4j-health.sh

# Add hourly health check
(sudo crontab -l 2>/dev/null; echo "0 * * * * /usr/local/bin/check-neo4j-health.sh") | sudo crontab -

echo "✓ Health monitoring configured (hourly)"

echo ""
echo "========================================="
echo "✅ Backup System Configured!"
echo "========================================="
echo ""
echo "Backup Schedule:"
echo "  - Daily dumps:      2:00 AM (to object storage)"
echo "  - Weekly snapshots: Sunday 3:00 AM (manual setup needed)"
echo "  - Quarterly tests:  1st Sunday of Jan/Apr/Jul/Oct"
echo "  - Health checks:    Every hour"
echo ""
echo "Next Steps:"
echo "1. Configure Swift object storage (see instructions above)"
echo "2. Test backup manually: sudo /usr/local/bin/neo4j-backup.sh"
echo "3. Verify backups: swift list neo4j-backups"
echo "4. Setup volume snapshots from management machine"
echo "5. Test restore: sudo /usr/local/bin/test-restore.sh"
echo ""
echo "View backup logs:"
echo "  tail -f /var/log/neo4j-backup.log"
echo ""
echo "View cron jobs:"
echo "  sudo crontab -l"
echo ""
