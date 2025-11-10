# AWS Lambda Email Forwarder

Complete setup guide for forwarding emails using AWS Lambda and SES.

## Overview

This system automatically forwards emails received at your domain to specified email addresses. When someone sends email to `contact@yourdomain.com`, it gets forwarded to your personal Gmail account.

**Current Domains:**
- `deviationlabs.com` (active) → Uses `index-deviation.js`
- `pensieves.com` (setup needed) → Uses `index-pensieves.js`

## Prerequisites

- AWS Account with appropriate permissions
- Domain registered and using Route 53 for DNS
- Basic knowledge of AWS Console

## Complete Setup Guide for Pensieves

### Step 1: Verify Your Domain in SES

1. **Open AWS SES Console**
   - Go to https://console.aws.amazon.com/ses/
   - Ensure you're in **us-east-1 (N. Virginia)** region

2. **Add Domain**
   - Click "Identities" in left sidebar
   - Click "Create identity"
   - Select "Domain" as identity type
   - Enter: `pensieves.com`
   - Check "Use a default DKIM signing key pair" 
   - Click "Create identity"

3. **Save the DNS Records**
   - AWS will display DNS records to add
   - Keep this tab open for next step

### Step 2: Configure DNS Records in Route 53

1. **Open Route 53 Console**
   - Go to https://console.aws.amazon.com/route53/
   - Click "Hosted zones"
   - Select `pensieves.com`

2. **Add MX Record (Required for receiving email)**
   ```
   Name: (leave empty)
   Type: MX
   TTL: 300
   Value: 10 inbound-smtp.us-east-1.amazonaws.com
   ```

3. **Add SES Verification Records**
   From the SES tab, add these DNS records:
   
   **Domain Verification:**
   ```
   Name: _amazonses.pensieves.com
   Type: TXT
   TTL: 300
   Value: [verification-string-from-aws]
   ```
   
   **DKIM Records (3 records):**
   ```
   Name: [key1]._domainkey.pensieves.com
   Type: CNAME
   TTL: 300
   Value: [key1].dkim.amazonses.com
   
   Name: [key2]._domainkey.pensieves.com
   Type: CNAME
   TTL: 300
   Value: [key2].dkim.amazonses.com
   
   Name: [key3]._domainkey.pensieves.com
   Type: CNAME
   TTL: 300
   Value: [key3].dkim.amazonses.com
   ```

4. **Wait for Verification**
   - Return to SES Console
   - Wait 5-10 minutes for DNS propagation
   - Refresh until domain shows "verified" status

### Step 3: Verify Sender Email Address

1. **In SES Console**
   - Click "Identities" in sidebar
   - Click "Create identity"
   - Select "Email address" as identity type
   - Enter: `lambda_forwarder@pensieves.com`
   - Click "Create identity"
   - Check email and click verification link

### Step 4: Create S3 Bucket for Email Storage

1. **Open S3 Console**
   - Go to https://console.aws.amazon.com/s3/
   - Click "Create bucket"

2. **Configure Bucket**
   - Name: `pensieves-email-bucket`
   - Region: **us-east-1**
   - Leave other settings as default
   - Click "Create bucket"

3. **Set Bucket Policy**
   - Open the bucket → Permissions → Bucket policy
   - Add this policy (replace `YOUR-ACCOUNT-ID`):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "AllowSESPuts",
         "Effect": "Allow",
         "Principal": {
           "Service": "ses.amazonaws.com"
         },
         "Action": "s3:PutObject",
         "Resource": "arn:aws:s3:::pensieves-email-bucket/*",
         "Condition": {
           "StringEquals": {
             "aws:Referer": "YOUR-ACCOUNT-ID"
           }
         }
       }
     ]
   }
   ```

### Step 5: Create IAM Role for Lambda

1. **Open IAM Console**
   - Go to https://console.aws.amazon.com/iam/
   - Click "Roles" → "Create role"

2. **Configure Role**
   - Service: Lambda
   - Permissions: Attach these policies:
     - `AWSLambdaBasicExecutionRole`
     - `AmazonSESFullAccess`
     - `AmazonS3ReadOnlyAccess`
   - Role name: `lambda-email-forwarder-role`

### Step 6: Deploy Lambda Function

1. **Open Lambda Console**
   - Go to https://console.aws.amazon.com/lambda/
   - Click "Create function"

2. **Configure Function**
   - Function name: `pensieves-email-forwarder`
   - Runtime: **Node.js 18.x**
   - Execution role: `lambda-email-forwarder-role`
   - Click "Create function"

3. **Upload Code**
   - In function code editor, replace all content with `index-pensieves.js`
   - Update the email mappings in `forwardMapping` section:
   ```javascript
   forwardMapping: {
     info: ["your-email+pensieves-info@gmail.com"],
     contact: ["your-email+pensieves-contact@gmail.com"],
     "@pensieves.com": ["your-email+pensieves@gmail.com"],
   }
   ```

4. **Configure Function Settings**
   - Timeout: 30 seconds
   - Memory: 256 MB
   - Click "Deploy"

### Step 7: Create SES Receipt Rule

1. **Return to SES Console**
   - Click "Rule Sets" in sidebar
   - Create new rule set if none exists
   - Click "Create Rule"

2. **Configure Rule**
   - **Step 1 - Recipients:**
     - Add: `pensieves.com`
   
   - **Step 2 - Actions:**
     - **Action 1:** S3
       - Bucket: `pensieves-email-bucket`
       - Object key prefix: `emailsPrefix/`
     
     - **Action 2:** Lambda
       - Function: `pensieves-email-forwarder`
       - Invocation type: Event
   
   - **Step 3 - Rule Details:**
     - Rule name: `pensieves-forwarder`
     - Enabled: ✓

3. **Activate Rule Set**
   - Select your rule set
   - Click "Set as Active Rule Set"

### Step 8: Test the Setup

1. **Send Test Email**
   - From external account (Gmail, etc.)
   - Send to: `info@pensieves.com`
   - Subject: "Test email forwarding"

2. **Monitor Results**
   - Check CloudWatch Logs for Lambda function
   - Verify email arrives at destination
   - Check S3 bucket for stored email

## Configuration Options

### Email Forwarding Rules

The `forwardMapping` object supports several patterns:

```javascript
forwardMapping: {
  // Exact username match
  "info": ["destination@gmail.com"],
  
  // Wildcard patterns
  "support.*": ["support-team@gmail.com"],
  
  // Domain catch-all
  "@pensieves.com": ["admin@gmail.com"],
  
  // Default fallback
  "@": ["fallback@gmail.com"]
}
```

### Advanced Configuration

```javascript
const defaultConfig = {
  fromEmail: "lambda_forwarder@pensieves.com",
  subjectPrefix: "[Pensieves] ",              // Optional prefix
  emailBucket: "pensieves-email-bucket",
  emailKeyPrefix: "emailsPrefix/",
  allowPlusSign: true,                        // Support email+tag@domain.com
  forwardMapping: { /* rules */ }
};
```

## Troubleshooting

### Domain Verification Issues
- **Problem:** Domain won't verify
- **Solution:** Check DNS records in Route 53, wait up to 72 hours for propagation

### Email Not Forwarding
- **Problem:** Emails sent but not forwarded
- **Solutions:**
  1. Check CloudWatch logs: `/aws/lambda/pensieves-email-forwarder`
  2. Verify SES rule set is active
  3. Confirm S3 bucket policy allows SES writes
  4. Check sender email is verified in SES

### Lambda Execution Errors
- **Problem:** Function fails with permission errors
- **Solutions:**
  1. Verify IAM role has required permissions
  2. Check S3 bucket exists and is accessible
  3. Confirm Lambda is in us-east-1 region

### Emails Going to Spam
- **Problem:** Forwarded emails marked as spam
- **Solutions:**
  1. Ensure DKIM records are properly configured
  2. Add SPF record: `"v=spf1 include:amazonses.com ~all"`
  3. Configure DMARC policy

## Monitoring and Maintenance

### CloudWatch Logs
Monitor Lambda function logs at:
- Log group: `/aws/lambda/pensieves-email-forwarder`
- Look for processing steps and any errors

### SES Metrics
Check SES Console for:
- Bounce rates
- Complaint rates  
- Delivery statistics

### S3 Storage Costs
- Emails are stored indefinitely by default
- Consider lifecycle policies to delete old emails
- Typical email: 10-50KB storage

## Security Best Practices

1. **Restrict S3 Access:** Only allow SES service
2. **Monitor Logs:** Set up CloudWatch alarms for errors
3. **Regular Review:** Audit forwarding rules periodically
4. **Backup Configuration:** Keep Lambda code in version control

## Cost Estimation

**Monthly costs for moderate usage (100 emails/month):**
- SES: $0.10 (receiving) + $0.10 (sending) = $0.20
- Lambda: $0.00 (free tier covers usage)
- S3: $0.02 (storage)
- **Total: ~$0.22/month**

## Support

For issues:
1. Check CloudWatch logs first
2. Verify all DNS records are correct
3. Ensure IAM permissions are properly configured
4. Test with simple forwarding rule before complex patterns