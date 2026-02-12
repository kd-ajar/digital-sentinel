#!/bin/bash
# AWS Cost Cleanup Script - Run to minimize costs

echo "=== AWS COST CLEANUP SCRIPT ==="

# 1. Stop all ECS services
echo "Stopping ECS services..."
for cluster in $(aws ecs list-clusters --query 'clusterArns[*]' --output text); do
    echo "Checking cluster: $cluster"
    for service in $(aws ecs list-services --cluster $cluster --query 'serviceArns[*]' --output text); do
        echo "Scaling down service: $service"
        aws ecs update-service --cluster $cluster --service $service --desired-count 0
    done
done

# 2. Delete MSK clusters (WARNING: This deletes data!)
echo "Listing MSK clusters for manual deletion:"
aws kafka list-clusters --query 'ClusterInfoList[*].[ClusterName,ClusterArn]' --output table

# 3. Stop EMR Serverless applications
echo "Stopping EMR Serverless applications..."
for app in $(aws emr-serverless list-applications --query 'applications[*].id' --output text); do
    echo "Stopping EMR Serverless app: $app"
    aws emr-serverless stop-application --application-id $app
done

# 4. Delete unassociated Elastic IPs
echo "Releasing unassociated Elastic IPs..."
for eip in $(aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].AllocationId' --output text); do
    echo "Releasing EIP: $eip"
    aws ec2 release-address --allocation-id $eip
done

# 5. List expensive resources for manual review
echo "=== EXPENSIVE RESOURCES TO REVIEW MANUALLY ==="
echo "NAT Gateways (≈$45/month each):"
aws ec2 describe-nat-gateways --query 'NatGateways[?State==`available`].[NatGatewayId,VpcId]' --output table

echo "Load Balancers (≈$18/month each):"
aws elbv2 describe-load-balancers --query 'LoadBalancers[*].[LoadBalancerName,LoadBalancerArn]' --output table

echo "=== CLEANUP COMPLETE ==="
echo "Review the resources above and delete manually if not needed."