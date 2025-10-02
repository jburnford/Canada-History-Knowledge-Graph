# SSH Key Setup for Arbutus Cloud

## Your Current SSH Key

**Public Key** (add this to Arbutus):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILfCmYi8a7st1ZZmAziUH/JRdbUJ0/FI7yGoFKHx4vsu jim.clifford@usask.ca
```

**Location**: `~/.ssh/id_ed25519` (private) and `~/.ssh/id_ed25519.pub` (public)

## Adding SSH Key to Arbutus

### Via Web Dashboard

1. Log in to https://arbutus.cloud.computecanada.ca/
2. Go to **Project** → **Compute** → **Key Pairs**
3. Click **Import Public Key**
4. Name: `jic823-usask`
5. Paste your public key (shown above)
6. Click **Import Key Pair**

### Via OpenStack CLI (Alternative)

```bash
openstack keypair create --public-key ~/.ssh/id_ed25519.pub jic823-usask
```

## Connecting to Your VM

Once the VM is created with your key:

```bash
# From WSL
ssh ubuntu@<FLOATING-IP>

# Or with specific key
ssh -i ~/.ssh/id_ed25519 ubuntu@<FLOATING-IP>
```

## Creating Additional Keys for Team Members

### For Each Team Member

```bash
# On their local machine (Linux/Mac/WSL)
ssh-keygen -t ed25519 -C "their.email@institution.ca"
# Press Enter to accept default location
# Set a strong passphrase

# Display their public key
cat ~/.ssh/id_ed25519.pub
```

### Add Team Member Keys to Arbutus VM

**Option 1: Add via cloud-init** (when creating VM):
```yaml
#cloud-config
users:
  - name: ubuntu
    ssh-authorized-keys:
      - ssh-ed25519 AAAA... jim.clifford@usask.ca
      - ssh-ed25519 AAAA... team.member1@institution.ca
      - ssh-ed25519 AAAA... team.member2@institution.ca
```

**Option 2: Add manually** (after VM is running):
```bash
# SSH to VM
ssh ubuntu@<FLOATING-IP>

# Add team member's public key
echo "ssh-ed25519 AAAA... team.member@institution.ca" >> ~/.ssh/authorized_keys

# Set correct permissions
chmod 600 ~/.ssh/authorized_keys
```

## SSH Configuration for Easy Access

Create `~/.ssh/config`:

```
# Arbutus Neo4j VM
Host neo4j-arbutus
    HostName <FLOATING-IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60

# SSH Tunnel for Neo4j Browser
Host neo4j-tunnel
    HostName <FLOATING-IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    LocalForward 7474 localhost:7474
    LocalForward 7687 localhost:7687
```

Then connect with:
```bash
# Direct SSH
ssh neo4j-arbutus

# SSH Tunnel
ssh -N neo4j-tunnel
# Access Neo4j Browser at http://localhost:7474
```

## Security Best Practices

### 1. Use Strong Passphrases
```bash
# Change passphrase on existing key
ssh-keygen -p -f ~/.ssh/id_ed25519
```

### 2. Restrict Key Permissions
```bash
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
chmod 700 ~/.ssh
```

### 3. Use SSH Agent (Avoid Typing Passphrase Repeatedly)
```bash
# Start SSH agent
eval $(ssh-agent)

# Add key to agent
ssh-add ~/.ssh/id_ed25519
# Enter passphrase once

# Keys loaded in agent
ssh-add -l
```

### 4. Rotate Keys Quarterly
```bash
# Generate new key
ssh-keygen -t ed25519 -C "jim.clifford@usask.ca" -f ~/.ssh/id_ed25519_new

# Add new key to VM
ssh-copy-id -i ~/.ssh/id_ed25519_new.pub ubuntu@<FLOATING-IP>

# Test new key works
ssh -i ~/.ssh/id_ed25519_new ubuntu@<FLOATING-IP>

# Remove old key from VM
ssh ubuntu@<FLOATING-IP> "sed -i '/OLD_KEY_COMMENT/d' ~/.ssh/authorized_keys"

# Move new key to default location
mv ~/.ssh/id_ed25519_new ~/.ssh/id_ed25519
mv ~/.ssh/id_ed25519_new.pub ~/.ssh/id_ed25519.pub
```

## Troubleshooting

### Connection Refused
```bash
# Check if VM is running
ping <FLOATING-IP>

# Check security group allows port 22 from your IP
openstack security group show neo4j-sg
```

### Permission Denied (publickey)
```bash
# Verify key is being offered
ssh -v ubuntu@<FLOATING-IP> 2>&1 | grep "Offering public key"

# Check permissions
ls -la ~/.ssh/id_ed25519*
# Should be: -rw------- (600) for private key
```

### Wrong Key Being Used
```bash
# Explicitly specify key
ssh -i ~/.ssh/id_ed25519 ubuntu@<FLOATING-IP>

# Or disable other keys temporarily
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 ubuntu@<FLOATING-IP>
```

## Backup Your SSH Keys

**Important**: Keep a secure backup of your private key!

```bash
# Encrypted backup
gpg -c ~/.ssh/id_ed25519
# Save id_ed25519.gpg to secure location

# To restore:
gpg -d id_ed25519.gpg > ~/.ssh/id_ed25519
chmod 600 ~/.ssh/id_ed25519
```

## Team Access Workflow

1. **Team member generates** their SSH key pair locally
2. **Team member sends** their public key to you (via secure channel)
3. **You add** their public key to VM's `~/.ssh/authorized_keys`
4. **Team member connects** using their private key
5. **Document** who has access in a team access log

### Team Access Log Template

```
# Neo4j Arbutus VM Access Log

| Name           | Email                    | Key Fingerprint      | Date Added | Date Removed |
|----------------|--------------------------|----------------------|------------|--------------|
| Jim Clifford   | jim.clifford@usask.ca    | SHA256:abc...        | 2025-10-02 | -            |
| Team Member 1  | member1@institution.ca   | SHA256:def...        | 2025-10-15 | -            |
```

---

**Next Steps**:
1. ✅ You already have an SSH key
2. Add your public key to Arbutus dashboard
3. Create VM and verify SSH access
4. Set up ~/.ssh/config for easy connections
5. Add team member keys as needed

**Your Public Key** (copy this to Arbutus):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILfCmYi8a7st1ZZmAziUH/JRdbUJ0/FI7yGoFKHx4vsu jim.clifford@usask.ca
```
