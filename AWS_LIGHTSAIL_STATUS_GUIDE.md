# AWS Lightsail Status Check Guide

## Quick Status Check

### Step 1: Authenticate AWS CLI

If you get "session expired" error, re-authenticate:

```bash
# Option 1: Using AWS SSO (Recommended)
aws sso login --profile default

# Option 2: Using AWS Access Keys
aws configure

# Then enter:
# AWS Access Key ID: [your-access-key]
# AWS Secret Access Key: [your-secret-key]
# Default region: ap-south-1  (or your preferred region)
# Default output format: json
```

### Step 2: Verify AWS Credentials

```bash
aws sts get-caller-identity
```

**Expected output:**
```json
{
    "UserId": "AIDAI...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/your-username"
}
```

### Step 3: List All Lightsail Instances

```bash
aws lightsail get-instances --region ap-south-1 --output table
```

**Sample output:**
```
--------------------------------
|       GetInstances           |
+------------------------------+
| Instances                    |
| Name       | State  | IP     |
+------------|--------|--------+
| openalgo   | running| 1.2.3.4|
+------------|--------|--------+
```

---

## Detailed Status Information

### Get Full Instance Details

```bash
# Get all instances
aws lightsail get-instances --region ap-south-1 --output json

# Get specific instance
aws lightsail get-instance --instance-name openalgo --region ap-south-1 --output json
```

### Check Instance Health

```bash
aws lightsail get-instance-health-status \
  --instance-name openalgo \
  --region ap-south-1 \
  --output json
```

**Example output:**
```json
{
    "instanceHealthStatuses": [
        {
            "instanceName": "openalgo",
            "instanceHealth": "Ok",
            "description": "The Lightsail instance is running normally."
        }
    ]
}
```

### Check Firewall Rules

```bash
aws lightsail get-instance-port-states \
  --instance-name openalgo \
  --region ap-south-1 \
  --output table
```

**Expected output for production:**
```
Port 22 (SSH):     open
Port 80 (HTTP):    open
Port 443 (HTTPS):  open
```

### View Instance Metrics (Performance)

```bash
# CPU Utilization (last 24 hours)
aws lightsail get-instance-metric-statistics \
  --instance-name openalgo \
  --metric-name CPUUtilization \
  --statistics Average \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --region ap-south-1

# Network In (bytes received)
aws lightsail get-instance-metric-statistics \
  --instance-name openalgo \
  --metric-name NetworkIn \
  --statistics Sum \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --region ap-south-1

# Network Out (bytes sent)
aws lightsail get-instance-metric-statistics \
  --instance-name openalgo \
  --metric-name NetworkOut \
  --statistics Sum \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --region ap-south-1
```

### Check Static IPs

```bash
aws lightsail get-static-ips --region ap-south-1 --output table
```

### Check Snapshots/Backups

```bash
aws lightsail get-instance-snapshots --region ap-south-1 --output table
```

---

## Automated Status Script

Run the comprehensive status check script:

```bash
./aws_lightsail_status.sh
```

This will automatically:
- ✅ Verify AWS CLI installation
- ✅ Check AWS credentials
- ✅ List all instances
- ✅ Show instance details
- ✅ Display health status
- ✅ Show firewall rules
- ✅ Display networking info
- ✅ Check backups/snapshots
- ✅ Show performance metrics
- ✅ Provide recommendations

---

## Instance Management Commands

### Start/Stop/Reboot Instance

```bash
# Reboot instance (keeps data)
aws lightsail reboot-instance --instance-name openalgo

# Stop instance (pauses billing for compute)
aws lightsail stop-instance --instance-name openalgo

# Start instance
aws lightsail start-instance --instance-name openalgo
```

### Access Instance via CLI

```bash
# Get SSH access details
aws lightsail get-instance-access-details \
  --instance-name openalgo \
  --protocol ssh

# Get RDP access details (Windows instances)
aws lightsail get-instance-access-details \
  --instance-name openalgo \
  --protocol rdp
```

### Manage Firewall Rules

```bash
# Open a port (e.g., 8080)
aws lightsail open-instance-public-ports \
  --instance-name openalgo \
  --port-info fromPort=8080,toPort=8080,protocol=tcp

# Close a port
aws lightsail close-instances-public-ports \
  --instance-name openalgo \
  --port-info fromPort=8080,toPort=8080,protocol=tcp
```

### Create/Manage Snapshots

```bash
# Create snapshot (backup)
aws lightsail create-instance-snapshot \
  --instance-snapshot-name backup-$(date +%Y%m%d) \
  --instance-name openalgo

# List snapshots
aws lightsail get-instance-snapshots

# Delete snapshot
aws lightsail delete-instance-snapshot \
  --instance-snapshot-name backup-20250217
```

### Allocate Static IP

```bash
# Allocate static IP
aws lightsail allocate-static-ip \
  --static-ip-name openalgo-ip

# Attach to instance
aws lightsail attach-static-ip \
  --static-ip-name openalgo-ip \
  --instance-name openalgo

# Detach static IP
aws lightsail detach-static-ip --static-ip-name openalgo-ip
```

---

## JSON Output Examples

### Get Instance Info (JSON)

```bash
aws lightsail get-instance --instance-name openalgo --output json
```

```json
{
    "instance": {
        "name": "openalgo",
        "arn": "arn:aws:lightsail:ap-south-1:123456789012:Instance/openalgo",
        "supportCode": "123456/987654",
        "createdAt": "2025-02-17T10:30:00.000000+00:00",
        "location": {
            "availabilityZone": "ap-south-1a",
            "regionName": "ap-south-1"
        },
        "resourceType": "Instance",
        "tags": [],
        "blueprint_id": "ubuntu_22_04",
        "blueprint_name": "Ubuntu 22.04 LTS",
        "bundleId": "medium_2_0",
        "isStaticIp": false,
        "publicIpAddress": "1.2.3.4",
        "privateIpAddress": "172.31.x.x",
        "hardware": {
            "cpuCount": 2,
            "disks": [
                {
                    "createdAt": "2025-02-17T10:30:00.000000+00:00",
                    "sizeInGb": 50,
                    "attachmentState": "attached"
                }
            ],
            "ramSizeInGb": 4.0
        },
        "state": "running",
        "username": "ubuntu",
        "sshKeyName": "LightsailDefaultKey"
    }
}
```

---

## Troubleshooting

### AWS CLI Not Found

```bash
# Install AWS CLI v2
# macOS
brew install awscli

# Ubuntu/Debian
sudo apt install awscli

# Or download from: https://aws.amazon.com/cli/
```

### Credentials Expired

```bash
# Re-authenticate
aws sso login --profile default

# Or reconfigure
aws configure
```

### Instance Not Found

```bash
# Check region
aws lightsail get-instances --region ap-south-1

# List all regions with instances
for region in ap-south-1 us-east-1 eu-west-1; do
  echo "Region: $region"
  aws lightsail get-instances --region $region 2>/dev/null || echo "  No instances"
done
```

### Access Denied

```bash
# Check IAM permissions
aws iam get-user

# Required permissions:
# - lightsail:GetInstances
# - lightsail:GetInstance
# - lightsail:GetInstanceHealthStatus
# - lightsail:GetInstancePortStates
# - lightsail:GetInstanceMetricStatistics
```

---

## Monitoring Dashboard

### Create Continuous Monitor

```bash
# Monitor CPU every 5 seconds
watch -n 5 'aws lightsail get-instance-metric-statistics \
  --instance-name openalgo \
  --metric-name CPUUtilization \
  --statistics Average \
  --start-time $(date -u -d 1hour ago +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --region ap-south-1 \
  --output table'
```

### Monitor OpenAlgo Application

After deployment, SSH and run:

```bash
ssh -i your-key.pem ubuntu@1.2.3.4

# Check application status
/opt/openalgo/monitor.sh

# View real-time logs
/opt/openalgo/manage.sh logs

# Check Docker containers
docker compose ps

# System metrics
docker stats
```

---

## Pricing & Cost Monitoring

### Check Instance Pricing

```bash
# Lightsail pricing
https://aws.amazon.com/lightsail/pricing/

# Medium instance (4GB RAM, 2 vCPU, 50GB SSD):
# ~ $20-25/month depending on region
```

### Estimate Monthly Cost

```bash
# Instance: $20/month
# Data transfer out: $0.01/GB (first 1TB free)
# Static IP (if used): $3/month (if not attached: $5/month)
# Snapshots: $0.05/GB/month
# Total estimate: $20-25/month
```

---

## Useful AWS CLI Aliases

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
# Lightsail shortcuts
alias lightsail-instances='aws lightsail get-instances --region ap-south-1 --output table'
alias lightsail-status='aws lightsail get-instance --instance-name openalgo --region ap-south-1 --output json | jq ".instance | {name, state, public_ip: .publicIpAddress, created: .createdAt}"'
alias lightsail-metrics='aws lightsail get-instance-metric-statistics --instance-name openalgo --metric-name CPUUtilization --statistics Average --start-time $(date -u -d 1hour ago +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 60 --region ap-south-1 --output table'
alias lightsail-health='aws lightsail get-instance-health-status --instance-name openalgo --region ap-south-1 --output json'
alias lightsail-firewall='aws lightsail get-instance-port-states --instance-name openalgo --region ap-south-1 --output table'
alias lightsail-reboot='aws lightsail reboot-instance --instance-name openalgo --region ap-south-1'
alias lightsail-stop='aws lightsail stop-instance --instance-name openalgo --region ap-south-1'
alias lightsail-start='aws lightsail start-instance --instance-name openalgo --region ap-south-1'

# Then reload shell
source ~/.bashrc  # or ~/.zshrc
```

---

## Complete Status Check One-Liner

```bash
echo "=== AWS Account ===" && \
aws sts get-caller-identity && \
echo "" && \
echo "=== Lightsail Instances ===" && \
aws lightsail get-instances --region ap-south-1 --output table && \
echo "" && \
echo "=== Instance Health ===" && \
aws lightsail get-instance-health-status --instance-name openalgo --region ap-south-1 && \
echo "" && \
echo "=== Firewall Rules ===" && \
aws lightsail get-instance-port-states --instance-name openalgo --region ap-south-1 --output table && \
echo "" && \
echo "=== Snapshots ===" && \
aws lightsail get-instance-snapshots --region ap-south-1 --output table
```

---

## Summary

Your Lightsail instance status can be checked using:

1. **Quick check**: `./aws_lightsail_status.sh`
2. **Web console**: https://lightsail.aws.amazon.com
3. **AWS CLI**: `aws lightsail get-instances`
4. **SSH direct**: `ssh -i key.pem ubuntu@IP`
5. **Application**: `https://algo.endoscopicspinehyderabad.in`

All tools are now available for managing your OpenAlgo deployment! 🚀

Let me know if you need any other questions!
