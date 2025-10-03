# Neo4j Arbutus Cloud - Maintenance Plan

## Server Information

**Instance Name:** neo4j-Canada
**Floating IP:** 206.12.90.118
**Private IP:** 192.168.149.254
**Instance Type:** p8-16gb (8 vCPU, 16GB RAM)
**Availability Zone:** Persistent_01

**Volumes:**
- Data: `/dev/vdc` → `/var/lib/neo4j-data` (500GB)
- Backups: `/dev/vdb` → `/var/backups/neo4j` (200GB)

**Neo4j Version:** 2025.09.0 Community Edition
**Database:** Canadian Census Knowledge Graph (1.39M nodes, 4.5M relationships)

**Access:**
- Browser: http://206.12.90.118:7474
- Bolt: bolt://206.12.90.118:7687
- Username: `neo4j`
- Password: (stored securely - see deployment notes)

---

## Daily Maintenance Tasks

### Automated (via Cron)

**Daily Backups (2:00 AM UTC)**
- Script: `/usr/local/bin/neo4j-backup.sh`
- Creates compressed database dump
- Retention: 7 days local storage
- Location: `/var/backups/neo4j/neo4j-YYYYMMDD-HHMMSS.dump.gz`
- Typical size: ~265MB compressed
- Downtime: ~1-2 minutes during backup

**Hourly Health Checks**
- Script: `/usr/local/bin/check-neo4j-health.sh`
- Monitors:
  - Neo4j service status (auto-restarts if down)
  - Data disk usage (warns at >80%)
  - Backup disk usage (warns at >80%)
  - HTTP endpoint availability
- Logs: `/var/log/neo4j-health.log`

### Manual (Check Weekly)

**Review Logs**
```bash
# SSH to server
ssh ubuntu@206.12.90.118

# Check backup log
sudo tail -50 /var/log/neo4j-backup.log

# Check health log
sudo tail -50 /var/log/neo4j-health.log

# Check Neo4j service log
sudo journalctl -u neo4j --since "1 week ago" | tail -100
```

**Verify Backups**
```bash
# List recent backups
ls -lh /var/backups/neo4j/

# Check backup disk usage
df -h /var/backups/neo4j
```

---

## Weekly Maintenance Tasks

### Monday Morning (First Thing)

**1. Check System Status**
```bash
ssh ubuntu@206.12.90.118

# Check Neo4j status
sudo systemctl status neo4j

# Check disk usage
df -h

# Check memory usage
free -h

# Check CPU and load
top -bn1 | head -20
```

**2. Review Backup Logs**
```bash
# Check last 7 days of backups
grep "Backup completed" /var/log/neo4j-backup.log | tail -7

# Verify backup sizes are consistent
ls -lh /var/backups/neo4j/ | tail -10
```

**3. Test Database Access**
```bash
# Quick query test
cypher-shell -u neo4j -p 'PASSWORD' 'MATCH (n) RETURN count(n) LIMIT 1;'

# Or via browser: http://206.12.90.118:7474
```

**4. Check for System Updates**
```bash
# Check available updates
sudo apt update
sudo apt list --upgradable
```

---

## Monthly Maintenance Tasks

### First Monday of Month

**1. Apply System Security Updates**
```bash
ssh ubuntu@206.12.90.118

# Update package lists
sudo apt update

# Install security updates
sudo apt upgrade -y

# Clean up
sudo apt autoremove -y
sudo apt clean

# Reboot if kernel updated
# Check with: ls /boot/vmlinuz-*
# If new kernel, schedule reboot during low-usage period
sudo reboot
```

**2. Review Disk Usage Trends**
```bash
# Data volume growth
df -h /var/lib/neo4j-data

# Backup volume
df -h /var/backups/neo4j

# Document monthly growth rate for capacity planning
```

**3. Test Backup Restoration**
```bash
# Create test restoration on dev machine (NOT on production!)
# Download latest backup
scp ubuntu@206.12.90.118:/var/backups/neo4j/neo4j-LATEST.dump.gz .

# Test restore locally to verify backup integrity
# (Instructions in QUICK_START.md)
```

**4. Review Access Logs**
```bash
# Check for unusual access patterns
sudo grep "Failed authentication" /var/lib/neo4j-data/logs/neo4j.log | tail -50

# Check for failed SSH attempts
sudo journalctl -u ssh --since "1 month ago" | grep "Failed"
```

---

## Quarterly Maintenance Tasks

### First Week of January, April, July, October

**1. Full Backup Restoration Test**
- Download latest backup to local machine
- Restore to test Neo4j instance
- Run comprehensive query tests
- Verify all data integrity
- Document results

**2. Security Audit**
```bash
# Review SSH authorized keys
cat ~/.ssh/authorized_keys

# Review firewall rules
sudo ufw status verbose

# Check for security updates
sudo apt update
sudo apt list --upgradable | grep security
```

**3. Performance Review**
```bash
# Query performance benchmarks
# Run standard query suite and document response times
# Compare with baseline (see NEO4J_DATABASE_COMPLETE.md)

# Check Neo4j metrics
# Access Neo4j Browser → http://206.12.90.118:7474
# Run: :sysinfo
# Document heap usage, page cache hit ratio, transactions/sec
```

**4. Capacity Planning**
```bash
# Calculate growth rates
# - Database size
# - Backup volume usage
# - Query complexity trends

# Project when resources will need expansion
```

**5. Update Documentation**
- Review and update all documentation
- Update team access list
- Document any configuration changes
- Update this maintenance plan as needed

---

## Annual Maintenance Tasks

### January (After New Year)

**1. Major Version Update Review**
- Check Neo4j release notes for new Community Edition version
- Test upgrade path on development instance
- Schedule production upgrade if beneficial
- Backup before any upgrade!

**2. Infrastructure Review**
- Review Arbutus allocation usage
- Consider VM flavor optimization
- Evaluate storage growth trends
- Plan capacity expansion if needed

**3. Disaster Recovery Drill**
- Simulate complete instance failure
- Practice full restoration from backup
- Document recovery time
- Update disaster recovery procedures

**4. Team Access Audit**
- Review all SSH authorized keys
- Remove access for former team members
- Update SSH key rotation schedule
- Document current team access list

---

## Emergency Procedures

### Neo4j Service Down

**Symptoms:** Browser/Bolt connections fail

**Quick Fix:**
```bash
ssh ubuntu@206.12.90.118
sudo systemctl restart neo4j

# Wait 30 seconds
sudo systemctl status neo4j

# Test connection
curl http://localhost:7474
```

**If restart fails:**
```bash
# Check logs for errors
sudo journalctl -u neo4j -n 100

# Check disk space
df -h

# Check memory
free -h

# If out of memory, reduce heap/page cache in /etc/neo4j/neo4j.conf
# Contact support if issue persists
```

### Disk Space Critical

**Data Volume >90% Full:**
```bash
# Check what's using space
sudo du -sh /var/lib/neo4j-data/*

# Check if transaction logs can be pruned
# (Neo4j automatically manages this, but can check)

# If critically full, consider expanding volume:
# 1. Create snapshot in Arbutus dashboard
# 2. Detach volume
# 3. Expand volume size
# 4. Reattach and resize filesystem
```

**Backup Volume >90% Full:**
```bash
# Reduce retention period temporarily
find /var/backups/neo4j -name "neo4j-*.dump.gz" -mtime +3 -delete

# Download old backups to archive
scp ubuntu@206.12.90.118:/var/backups/neo4j/neo4j-OLD*.dump.gz .

# Delete old backups from server
ssh ubuntu@206.12.90.118 "sudo rm /var/backups/neo4j/neo4j-OLD*.dump.gz"
```

### Instance Unreachable

**Cannot SSH or access Neo4j:**

1. Check Arbutus dashboard - is instance running?
2. Check security group rules - is your IP allowed?
3. Check floating IP association
4. Try console access via Arbutus dashboard
5. If all else fails, restore from backup to new instance

**Recovery Steps:**
```bash
# 1. Create new instance (see QUICK_START.md)
# 2. Download latest backup from Arbutus object storage OR local archive
# 3. Follow restoration steps in QUICK_START.md
# 4. Update floating IP association
# 5. Test access and data integrity
```

### Backup Failed

**Backup script errors in log:**
```bash
# Check backup log
sudo tail -100 /var/log/neo4j-backup.log

# Common issues:
# - Disk full: Clean up old backups
# - Neo4j won't stop: Check for long-running queries
# - Permission errors: Check neo4j user permissions

# Manual backup:
sudo systemctl stop neo4j
sudo -u neo4j neo4j-admin database dump neo4j --to-path=/var/backups/neo4j
sudo systemctl start neo4j
```

---

## Monitoring Checklist

### Daily (Automated)
- ✅ Neo4j service running
- ✅ Disk usage <80%
- ✅ HTTP endpoint responding
- ✅ Daily backup completed

### Weekly (Manual - 15 minutes)
- ✅ Review backup logs
- ✅ Verify backup file sizes
- ✅ Test database query
- ✅ Check system resource usage

### Monthly (Manual - 1 hour)
- ✅ Apply security updates
- ✅ Review disk usage trends
- ✅ Test backup restoration
- ✅ Review access logs
- ✅ Document metrics

### Quarterly (Manual - 3 hours)
- ✅ Full backup restoration test
- ✅ Security audit
- ✅ Performance benchmarks
- ✅ Capacity planning review
- ✅ Documentation update

### Annual (Manual - 1 day)
- ✅ Version update review
- ✅ Infrastructure optimization
- ✅ Disaster recovery drill
- ✅ Team access audit

---

## Key Performance Indicators

### Database Health
- **Node Count:** 1,392,059 (baseline)
- **Relationship Count:** ~4.5M (baseline)
- **Database Size:** ~2.2GB (baseline)
- **Compressed Backup:** ~265MB (baseline)

### Performance Targets
- **Simple Node Count Query:** <100ms
- **Complex Multi-hop Query:** <5s
- **Backup Time:** <2 minutes
- **Restore Time:** <1 minute
- **Service Restart:** <30 seconds

### Resource Utilization
- **Data Disk Usage:** Monitor growth rate, plan expansion at 70%
- **Backup Disk Usage:** Should stay <10% with 7-day retention
- **Memory Usage:** ~14GB (6GB heap + 8GB page cache)
- **CPU:** Typically <20%, spikes during queries normal

### Availability Targets
- **Uptime:** 99%+ (excluding scheduled maintenance)
- **Backup Success Rate:** 100%
- **RTO (Recovery Time Objective):** 2 hours
- **RPO (Recovery Point Objective):** 24 hours (daily backups)

---

## Contact Information

**Primary Administrator:**
- Name: Jim Clifford
- Institution: University of Saskatchewan
- Email: jim.clifford@usask.ca

**Support Resources:**
- **Arbutus Cloud Support:** support@tech.alliancecan.ca
- **Neo4j Community:** https://community.neo4j.com
- **Project Repository:** https://github.com/jburnford/Canada-History-Knowledge-Graph

**Escalation:**
- Minor issues: Check logs, try restart
- Moderate issues: Review this maintenance plan
- Major issues: Contact Arbutus support
- Data loss: Restore from backup immediately

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-10-03 | Initial deployment and maintenance plan | Jim Clifford |
| | Automated backups configured (daily 2AM) | |
| | Health monitoring configured (hourly) | |

---

**Last Reviewed:** 2025-10-03
**Next Review Due:** 2026-01-03 (Quarterly)
