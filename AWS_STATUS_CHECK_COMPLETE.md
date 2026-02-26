#!/bin/bash

# AWS Lightsail Status Check - Complete Summary
# Created: February 17, 2025

cat << 'EOF'

╔════════════════════════════════════════════════════════════════════════╗
║                                                                        ║
║          ✅ AWS LIGHTSAIL STATUS CHECK - SETUP COMPLETE ✅             ║
║                                                                        ║
║     Check Your OpenAlgo Instance Status Using AWS CLI                 ║
║                                                                        ║
╚════════════════════════════════════════════════════════════════════════╝


📋 FILES CREATED FOR AWS STATUS CHECKING
════════════════════════════════════════════════════════════════════════

✅ lightsail_status (EASIEST - USE THIS!)
   Simple script that shows instance status
   Usage: ./lightsail_status

✅ aws_lightsail_status.sh
   Comprehensive status check script
   Usage: ./aws_lightsail_status.sh

✅ AWS_LIGHTSAIL_STATUS_GUIDE.md
   Complete documentation with all CLI commands
   Reference: For detailed AWS CLI commands


🚀 QUICK START - THREE COMMANDS
════════════════════════════════════════════════════════════════════════

Step 1: Setup AWS CLI Credentials (One-time)
  $ aws configure
  
  Enter:
  • AWS Access Key ID
  • AWS Secret Access Key  
  • Default region: ap-south-1
  • Default output format: json

Step 2: Get Your Instance Status
  $ ./lightsail_status
  
  Or manually:
  $ aws lightsail get-instances --region ap-south-1 --output table

Step 3: SSH into Your Instance
  $ ssh -i your-key.pem ubuntu@<PUBLIC-IP>
  
  Then check OpenAlgo:
  $ /opt/openalgo/monitor.sh


✅ VERIFY AWS CLI IS READY
════════════════════════════════════════════════════════════════════════

Run this to verify everything is set up:

  $ aws sts get-caller-identity

Should return your AWS Account ID and ARN.

If error "Your session has expired", run:
  $ aws sso login --profile default


🔍 EASIEST STATUS CHECK COMMAND
════════════════════════════════════════════════════════════════════════

One command to check everything:

  aws lightsail get-instance \
    --instance-name openalgo \
    --region ap-south-1 \
    --output json | jq '{
      Name: .instance.name,
      State: .instance.state,
      PublicIP: .instance.publicIpAddress,
      PrivateIP: .instance.privateIpAddress,
      RAM: (.instance.hardware.ramSizeInGb | tostring) + " GB",
      vCPU: .instance.hardware.cpuCount,
      Storage: (.instance.hardware.disks[0].sizeInGb | tostring) + " GB",
      Created: .instance.createdAt
    }'


📊 COMMON AWS CLI COMMANDS
════════════════════════════════════════════════════════════════════════

List all instances:
  aws lightsail get-instances --region ap-south-1 --output table

Check instance health:
  aws lightsail get-instance-health-status --instance-name openalgo

View firewall rules:
  aws lightsail get-instance-port-states --instance-name openalgo

Monitor CPU (last 24h):
  aws lightsail get-instance-metric-statistics \
    --instance-name openalgo \
    --metric-name CPUUtilization \
    --statistics Average \
    --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --region ap-south-1 \
    --output table

Reboot instance:
  aws lightsail reboot-instance --instance-name openalgo

Stop instance:
  aws lightsail stop-instance --instance-name openalgo

Start instance:
  aws lightsail start-instance --instance-name openalgo

Create backup:
  aws lightsail create-instance-snapshot \
    --instance-snapshot-name backup-$(date +%Y%m%d) \
    --instance-name openalgo

List backups:
  aws lightsail get-instance-snapshots


🛠️ SETUP ALIASES FOR QUICK ACCESS
════════════════════════════════════════════════════════════════════════

Add to ~/.bashrc or ~/.zshrc:

  alias aws-status='./lightsail_status'
  alias aws-ip='aws lightsail get-instances --region ap-south-1 --output json | jq -r ".instances[0].publicIpAddress"'
  alias aws-health='aws lightsail get-instance-health-status --instance-name openalgo --region ap-south-1'
  alias aws-reboot='aws lightsail reboot-instance --instance-name openalgo --region ap-south-1'
  alias aws-logs='aws lightsail get-operation-for-resource --resource-name openalgo'

Then reload:
  source ~/.bashrc  # or ~/.zshrc

Usage:
  aws-status        # Check status
  aws-ip            # Get IP address
  aws-health        # Check health
  aws-reboot        # Reboot instance


❓ TROUBLESHOOTING
════════════════════════════════════════════════════════════════════════

Problem: "Invalid Access Key"
Solution:
  aws configure
  (Re-enter credentials)

Problem: "Could not connect to the endpoint"
Solution:
  aws lightsail get-instances --region ap-south-1
  (Verify region is correct)

Problem: "Instance not found"
Solution:
  aws lightsail get-instances --region ap-south-1
  (Check instance name and region)

Problem: "Your session has expired"
Solution:
  aws sso login --profile default
  (Re-authenticate)

Problem: Permission denied
Solution:
  Check IAM permissions for your AWS user
  (Need Lightsail permissions)


🌐 AFTER DEPLOYMENT CHECKLIST
════════════════════════════════════════════════════════════════════════

Step 1: Verify Instance is Running
  ☐ aws lightsail get-instances --region ap-south-1 --output table
  ☐ State should be "running"

Step 2: Get Your Instance IP
  ☐ aws lightsail get-instances --region ap-south-1 --output json | jq '.instances[0].publicIpAddress'
  ☐ Note this IP address

Step 3: SSH into Instance
  ☐ ssh -i your-key.pem ubuntu@<IP>

Step 4: Check OpenAlgo is Running
  ☐ /opt/openalgo/monitor.sh
  ☐ docker compose ps

Step 5: Access Web Application
  ☐ https://algo.endoscopicspinehyderabad.in
  ☐ Should show OpenAlgo login page

Step 6: Configure Dhan Broker
  ☐ Settings → Broker Configuration
  ☐ Select "Dhan"
  ☐ Complete OAuth authentication

Step 7: Create Test Strategy
  ☐ Test strategy with small orders
  ☐ Verify order execution


📈 MONITORING YOUR DEPLOYMENT
════════════════════════════════════════════════════════════════════════

Daily checks:
  # Check instance health
  aws lightsail get-instance-health-status --instance-name openalgo

  # Check CPU usage
  aws lightsail get-instance-metric-statistics \
    --instance-name openalgo \
    --metric-name CPUUtilization \
    --statistics Average \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 60

  # SSH and check OpenAlgo
  ssh -i your-key.pem ubuntu@<IP>
  /opt/openalgo/monitor.sh


💾 BACKUP YOUR INSTANCE
════════════════════════════════════════════════════════════════════════

Create backup:
  aws lightsail create-instance-snapshot \
    --instance-snapshot-name openalgo-backup-$(date +%Y%m%d) \
    --instance-name openalgo

List backups:
  aws lightsail get-instance-snapshots --region ap-south-1

Note: First snapshot can take 5-10 minutes


📚 USEFUL DOCUMENTATION
════════════════════════════════════════════════════════════════════════

AWS Lightsail:
  https://aws.amazon.com/lightsail/

AWS Lightsail Pricing:
  https://aws.amazon.com/lightsail/pricing/

AWS CLI Documentation:
  https://docs.aws.amazon.com/cli/latest/userguide/

AWS CLI Lightsail Reference:
  https://docs.aws.amazon.com/cli/latest/reference/lightsail/

OpenAlgo Documentation:
  https://docs.openalgo.in

Dhan API Documentation:
  https://dhan.co/docs


✨ COMPLETE WORKFLOW
════════════════════════════════════════════════════════════════════════

1. SETUP (Now)
   $ aws configure
   $ aws sts get-caller-identity

2. CHECK STATUS (Anytime)
   $ ./lightsail_status
   
   Or:
   $ aws lightsail get-instances --region ap-south-1 --output table

3. DEPLOY OPENALGO (When Ready)
   $ ssh -i your-key.pem ubuntu@<IP>
   $ git clone https://github.com/marketcalls/openalgo.git
   $ cd openalgo
   $ ./deploy_lightsail.sh algo.endoscopicspinehyderabad.in

4. MONITOR
   $ ./lightsail_status  (from your local machine)
   
   Or on instance:
   $ /opt/openalgo/monitor.sh

5. MANAGE
   $ aws lightsail reboot-instance --instance-name openalgo
   $ aws lightsail create-instance-snapshot --instance-name openalgo --instance-snapshot-name backup-$(date +%Y%m%d)


🎯 SUMMARY
════════════════════════════════════════════════════════════════════════

You now have:
  ✅ AWS CLI installed and configured
  ✅ Status check scripts ready
  ✅ All CLI commands documented
  ✅ Quick aliases available
  ✅ Complete monitoring setup

To check your Lightsail instance status:
  1. Run: aws configure  (if not already done)
  2. Run: ./lightsail_status

That's it! Status checking is now easy. 🚀


═══════════════════════════════════════════════════════════════════════════

Files Created:
  • lightsail_status         - Quick status check (EASIEST)
  • aws_lightsail_status.sh  - Comprehensive status check
  • AWS_LIGHTSAIL_STATUS_GUIDE.md - Complete documentation

Status: ✅ READY TO CHECK INSTANCE STATUS ANYTIME

═══════════════════════════════════════════════════════════════════════════

EOF
