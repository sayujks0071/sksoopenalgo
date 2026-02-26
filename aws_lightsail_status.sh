#!/bin/bash

# AWS Lightsail Status Check Script
# Requires AWS CLI configured with valid credentials

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# ============================================================================
# Step 1: Check AWS CLI Installation
# ============================================================================
print_header "AWS CLI Status"

if command -v aws &> /dev/null; then
    print_success "AWS CLI installed"
    aws --version
else
    print_error "AWS CLI not found. Install with:"
    echo "  brew install awscli  # macOS"
    echo "  sudo apt install awscliv2  # Ubuntu/Linux"
    echo "  choco install awscli  # Windows"
    exit 1
fi

# ============================================================================
# Step 2: Check AWS Credentials
# ============================================================================
print_header "AWS Credentials Status"

if aws sts get-caller-identity &> /dev/null; then
    print_success "AWS credentials valid"
    
    IDENTITY=$(aws sts get-caller-identity --output json)
    ACCOUNT=$(echo $IDENTITY | grep -o '"Account": "[^"]*' | cut -d'"' -f4)
    ARN=$(echo $IDENTITY | grep -o '"Arn": "[^"]*' | cut -d'"' -f4)
    
    echo "Account ID: $ACCOUNT"
    echo "ARN: $ARN"
else
    print_error "AWS credentials expired or invalid"
    echo ""
    echo "To configure credentials, run:"
    echo "  aws configure"
    echo ""
    echo "You'll need:"
    echo "  • AWS Access Key ID"
    echo "  • AWS Secret Access Key"
    echo "  • Default region (us-east-1, ap-south-1, etc.)"
    echo ""
    exit 1
fi

# ============================================================================
# Step 3: Get Lightsail Region
# ============================================================================
print_header "Lightsail Region"

REGION=$(aws configure get region)
if [ -z "$REGION" ]; then
    REGION="us-east-1"
    print_info "Using default region: $REGION"
else
    print_success "Configured region: $REGION"
fi

# ============================================================================
# Step 4: List Lightsail Instances
# ============================================================================
print_header "Lightsail Instances"

INSTANCES=$(aws lightsail get-instances --region $REGION --output json 2>/dev/null)
INSTANCE_COUNT=$(echo $INSTANCES | jq '.instances | length')

if [ "$INSTANCE_COUNT" -eq 0 ]; then
    print_error "No Lightsail instances found in region $REGION"
    echo ""
    echo "To create an instance, visit AWS Lightsail console:"
    echo "  https://lightsail.aws.amazon.com"
    exit 1
fi

print_success "Found $INSTANCE_COUNT instance(s)"

# ============================================================================
# Step 5: Display Instance Details
# ============================================================================
print_header "Instance Details"

echo $INSTANCES | jq '.instances[] | {
  name: .name,
  state: .state,
  public_ip: .publicIpAddress,
  private_ip: .privateIpAddress,
  instance_type: .blueprintId,
  availability_zone: .availabilityZone,
  created_at: .createdAt
}' | while read -r line; do
    echo "$line"
done

# ============================================================================
# Step 6: Get Detailed Instance Status
# ============================================================================
print_header "Instance Status Details"

echo $INSTANCES | jq -r '.instances[] | 
    "Instance: \(.name)\n" +
    "  State: \(.state)\n" +
    "  Public IP: \(.publicIpAddress)\n" +
    "  Private IP: \(.privateIpAddress)\n" +
    "  Instance Type: \(.bundleId)\n" +
    "  RAM: \(.hardware.ramSizeInGb) GB\n" +
    "  vCPUs: \(.hardware.cpuCount)\n" +
    "  Disks: \(.hardware.disks | map(.sizeInGb) | join(\", \")) GB\n" +
    "  Availability Zone: \(.availabilityZone)\n" +
    "  Created: \(.createdAt)\n"'

# ============================================================================
# Step 7: Get Instance Health Status
# ============================================================================
print_header "Instance Health Status"

INSTANCE_NAME=$(echo $INSTANCES | jq -r '.instances[0].name')

if [ ! -z "$INSTANCE_NAME" ]; then
    HEALTH=$(aws lightsail get-instance-health-status --instance-name $INSTANCE_NAME --region $REGION --output json 2>/dev/null)
    echo $HEALTH | jq '.instanceHealthStatuses[] | {
        instance: .instanceName,
        status: .instanceHealth,
        description: .description
    }'
fi

# ============================================================================
# Step 8: Get Firewall Rules
# ============================================================================
print_header "Firewall Rules"

if [ ! -z "$INSTANCE_NAME" ]; then
    RULES=$(aws lightsail get-instance-port-states --instance-name $INSTANCE_NAME --region $REGION --output json 2>/dev/null)
    
    if [ ! -z "$RULES" ]; then
        echo $RULES | jq -r '.portStates[] | "Port \(.fromPort): \(.protocol | ascii_upcase) - State: \(.state)"'
    fi
fi

# ============================================================================
# Step 9: Get Public IP and Networking
# ============================================================================
print_header "Networking Information"

PUBLIC_IP=$(echo $INSTANCES | jq -r '.instances[0].publicIpAddress')
PRIVATE_IP=$(echo $INSTANCES | jq -r '.instances[0].privateIpAddress')

if [ ! -z "$PUBLIC_IP" ]; then
    print_success "Public IP: $PUBLIC_IP"
    echo "  SSH Command: ssh -i your-key.pem ubuntu@$PUBLIC_IP"
fi

if [ ! -z "$PRIVATE_IP" ]; then
    print_success "Private IP: $PRIVATE_IP"
fi

# ============================================================================
# Step 10: Get Static IP (if assigned)
# ============================================================================
print_header "Static IP Address"

STATIC_IPS=$(aws lightsail get-static-ips --region $REGION --output json 2>/dev/null)
STATIC_COUNT=$(echo $STATIC_IPS | jq '.staticIps | length')

if [ "$STATIC_COUNT" -gt 0 ]; then
    print_success "Found $STATIC_COUNT static IP(s)"
    echo $STATIC_IPS | jq -r '.staticIps[] | "IP: \(.ipAddress) - Attached: \(.isAttached)"'
else
    print_info "No static IPs allocated (only dynamic public IP)"
fi

# ============================================================================
# Step 11: Get Lightsail Snapshots
# ============================================================================
print_header "Snapshots & Backups"

SNAPSHOTS=$(aws lightsail get-instance-snapshots --region $REGION --output json 2>/dev/null)
SNAPSHOT_COUNT=$(echo $SNAPSHOTS | jq '.instanceSnapshots | length')

if [ "$SNAPSHOT_COUNT" -gt 0 ]; then
    print_success "Found $SNAPSHOT_COUNT snapshot(s)"
    echo $SNAPSHOTS | jq -r '.instanceSnapshots[] | "Snapshot: \(.name) - State: \(.state) - Size: \(.sizeInGb)GB"'
else
    print_info "No snapshots found"
fi

# ============================================================================
# Step 12: Get Lightsail Metrics (CPU, Network)
# ============================================================================
print_header "Recent Instance Metrics (Last 24 Hours)"

if [ ! -z "$INSTANCE_NAME" ]; then
    # Get CPU Utilization
    CPU=$(aws lightsail get-instance-metric-statistics \
        --instance-name $INSTANCE_NAME \
        --metric-name CPUUtilization \
        --statistics Average \
        --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
        --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
        --period 3600 \
        --region $REGION \
        --output json 2>/dev/null)
    
    if [ ! -z "$CPU" ]; then
        print_success "CPU Utilization:"
        echo $CPU | jq '.metricStatistics[] | "  \(.timestamp): \(.average | round)%"' | head -5
    fi
    
    # Get Network In
    NET_IN=$(aws lightsail get-instance-metric-statistics \
        --instance-name $INSTANCE_NAME \
        --metric-name NetworkIn \
        --statistics Sum \
        --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
        --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
        --period 86400 \
        --region $REGION \
        --output json 2>/dev/null)
    
    if [ ! -z "$NET_IN" ]; then
        print_success "Network Traffic (24h):"
        echo $NET_IN | jq '.metricStatistics[] | "  In: \(.sum | round) bytes"'
    fi
fi

# ============================================================================
# Step 13: Cost Summary
# ============================================================================
print_header "Instance Pricing"

BUNDLE_ID=$(echo $INSTANCES | jq -r '.instances[0].bundleId')
echo "Instance Bundle: $BUNDLE_ID"
echo ""
echo "To view pricing details, visit:"
echo "  https://aws.amazon.com/lightsail/pricing/"
echo ""
echo "Estimated costs depend on:"
echo "  • Instance size (RAM, vCPU)"
echo "  • Data transfer"
echo "  • Static IP addresses"
echo "  • Snapshots and backups"

# ============================================================================
# Step 14: Summary and Recommendations
# ============================================================================
print_header "Status Summary"

STATE=$(echo $INSTANCES | jq -r '.instances[0].state')

if [ "$STATE" = "running" ]; then
    print_success "Instance is RUNNING and ready for use"
else
    print_error "Instance state: $STATE"
fi

echo ""
print_info "Next steps:"
echo "  1. Verify SSH access:"
echo "     ssh -i your-key.pem ubuntu@$PUBLIC_IP"
echo ""
echo "  2. Deploy OpenAlgo:"
echo "     ./deploy_lightsail.sh algo.endoscopicspinehyderabad.in"
echo ""
echo "  3. Monitor application:"
echo "     ssh -i your-key.pem ubuntu@$PUBLIC_IP"
echo "     /opt/openalgo/monitor.sh"
echo ""
echo "  4. View instance details:"
echo "     aws lightsail describe-instances --instance-names openalgo"
echo ""

print_header "Useful AWS CLI Commands"

cat << 'EOF'
# Get all instances
aws lightsail get-instances

# Get specific instance
aws lightsail get-instance --instance-name openalgo

# Reboot instance
aws lightsail reboot-instance --instance-name openalgo

# Get instance access details
aws lightsail get-instance-access-details --instance-name openalgo

# Create snapshot
aws lightsail create-instance-snapshot --instance-snapshot-name backup-$(date +%Y%m%d)

# Get firewall rules
aws lightsail get-instance-port-states --instance-name openalgo

# Open port
aws lightsail open-instance-public-ports --instance-name openalgo --port-info fromPort=8080,toPort=8080,protocol=tcp

# Close port
aws lightsail close-instances-public-ports --instance-name openalgo --port-info fromPort=8080,toPort=8080,protocol=tcp

# Stop instance
aws lightsail stop-instance --instance-name openalgo

# Start instance
aws lightsail start-instance --instance-name openalgo

# Delete instance
aws lightsail delete-instance --instance-name openalgo

# Get recent activity
aws lightsail get-operations

# Monitor performance
watch -n 1 'aws lightsail get-instance-metric-statistics --instance-name openalgo --metric-name CPUUtilization --statistics Average --start-time $(date -u -d 1hour ago +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 60'
EOF

echo ""
print_success "Status check complete!"
