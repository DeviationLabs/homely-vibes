# AWS Lambda Email Forwarder

Complete setup guide for forwarding emails using AWS Lambda and SES.

## Overview

This system automatically forwards emails received at your domain to specified email addresses. When someone sends email to `contact@yourdomain.com`, it gets forwarded to your personal Gmail account.

## Prerequisites

- AWS Account with appropriate permissions
- Domain registered and using Route 53 for DNS
- Basic knowledge of AWS Console
- Node.js knowledge for customizing email mappings

## Complete Setup Guide

### Step 1: Prepare Lambda Function Code

1. **Copy the base Lambda function**
   - Start with `index-deviation.js` as your template
   - Create a new file for your domain (e.g., `index-yourdomain.js`)

2. **Update configuration for your domain**
   ```javascript
   const defaultConfig = {
     fromEmail: "lambda_forwarder@yourdomain.com",
     subjectPrefix: "",
     emailBucket: "yourdomain-email-bucket",
     emailKeyPrefix: "emailsPrefix/",
     allowPlusSign: true,
     forwardMapping: {
       // Your email mappings
       info: ["your-email+info@gmail.com"],
       contact: ["your-email+contact@gmail.com"],
       admin: ["your-email+admin@gmail.com"],
       
       // Domain catch-all
       "@yourdomain.com": ["your-email@gmail.com"],
       "@www.yourdomain.com": ["your-email+www@gmail.com"],
       
       // Default fallback
       "@": ["your-email+default@gmail.com"],
     },
   };
   ```

### Step 2: Verify Your Domain in SES

1. **Open AWS SES Console**
   - Go to https://console.aws.amazon.com/ses/
   - Ensure you're in **us-east-1 (N. Virginia)** region

2. **Add Domain Identity**
   - Click "Identities" in left sidebar
   - Click "Create identity"
   - Select "Domain" as identity type
   - Enter your domain: `yourdomain.com`
   - Keep "Assign a default configuration set" checked ✓
   - Under DKIM settings, select "Easy DKIM" (recommended)
   - Keep "DKIM signatures" enabled ✓
   - Click "Create identity"

3. **DNS Records Setup**
   - After creation, you'll see "Action required" message
   - AWS will display DKIM CNAME records that need to be added
   - Keep this tab open - you'll need these records for Route 53

### Step 3: Configure DNS Records in Route 53

1. **Open Route 53 Console**
   - Go to https://console.aws.amazon.com/route53/
   - Click "Hosted zones"
   - Select your domain

2. **Add MX Record (Required for receiving email)**
   - Click "Create record"
   - Leave Name field empty (for root domain)
   - Select Type: MX
   - Set TTL: 300
   - Enter Value: `10 inbound-smtp.us-east-1.amazonaws.com`
   - Click "Create records"

3. **Add DKIM CNAME Records**
   - Copy the 3 DKIM CNAME records from SES console
   - For each record, click "Create record" in Route 53:
     - Name: `[dkim-key]._domainkey` (without the domain suffix)
     - Type: CNAME
     - TTL: 300
     - Value: `[dkim-key].dkim.amazonses.com`
   - Repeat for all 3 DKIM records

4. **Wait for Verification**
   - DNS propagation takes 5-10 minutes
   - Return to SES Console → Identities
   - Refresh until domain shows "Verified" status
   - Look for green checkmarks next to DKIM authentication

### Step 4: Verify Sender Email Address

1. **In SES Console**
   - Click "Identities" in sidebar
   - Click "Create identity"
   - Select "Email address" as identity type
   - Enter: `lambda_forwarder@yourdomain.com`
   - Click "Create identity"
   - Check your email and click verification link

### Step 5: Create S3 Bucket for Email Storage

1. **Open S3 Console**
   - Go to https://console.aws.amazon.com/s3/
   - Click "Create bucket"

2. **Configure Bucket**
   - Name: `yourdomain-email-bucket`
   - Region: **us-east-1** (required)
   - Leave other settings as default
   - Click "Create bucket"

3. **Set Bucket Policy**
   - Open the bucket → Permissions → Bucket policy
   - Add this policy:

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
               "Resource": "arn:aws:s3:::yourdomain-email-bucket/*"
           },
           {
               "Sid": "AllowLambdaRead",
               "Effect": "Allow",
               "Principal": {
                   "Service": "lambda.amazonaws.com"
               },
               "Action": "s3:GetObject",
               "Resource": "arn:aws:s3:::yourdomain-email-bucket/*"
           }
       ]
   }
   ```

### Step 6: Create IAM Role for Lambda

1. **Open IAM Console**
   - Go to https://console.aws.amazon.com/iam/
   - Click "Roles" → "Create role"

2. **Configure Role**
   - Select "Lambda" service
   - Attach these policies:
     - `AWSLambdaBasicExecutionRole`
     - `AmazonSESFullAccess`
     - `AmazonS3ReadOnlyAccess`
   - Role name: `lambda-email-forwarder-role`
   - Click "Create role"

### Step 7: Deploy Lambda Function

1. **Open Lambda Console**
   - Go to https://console.aws.amazon.com/lambda/
   - Click "Create function"

2. **Configure Function**
   - Function name: `yourdomain-email-forwarder`
   - Runtime: **Node.js 18.x**
   - Execution role: Use existing role → `lambda-email-forwarder-role`
   - Click "Create function"

3. **Upload Code**
   - Go to "Code" tab
   - Delete default code
   - Copy and paste your customized `index-yourdomain.js` code
   - Click "Deploy"

4. **Configure Function Settings**
   - Go to "Configuration" → "General configuration"
   - Memory: 256 MB
   - Timeout: 30 seconds
   - Click "Save"

### Step 8: Create SES Receipt Rule

1. **Return to SES Console**
   - Go to "Configuration" → "Email receiving" → "Receipt rules"
   - Select existing rule set or create new one

2. **Create Rule**
   - Click "Create rule"
   - **Step 1 - Recipients:** Add your domain (e.g., `yourdomain.com`)
   - **Step 2 - Actions:** 
     - **Action 1:** Lambda
       - Function: `yourdomain-email-forwarder`
       - Invocation type: Event
     - **Action 2:** S3
       - Bucket: `yourdomain-email-bucket`
       - Object key prefix: `emailsPrefix/`
   - **Step 3 - Rule Details:** 
     - Rule name: `yourdomain-forwarder`
     - Enabled: ✓
   - Click "Create rule"

3. **Activate Rule Set**
   - Ensure your rule set is marked as "Active"
   - If not, select it and click "Set as active rule set"

### Step 9: Test Email Forwarding

1. **Send Test Email**
   - From external email account (Gmail, etc.)
   - Send to: `info@yourdomain.com`
   - Subject: "Test email forwarding"

2. **Monitor Results**
   - Check destination email for forwarded message
   - Monitor CloudWatch logs: `/aws/lambda/yourdomain-email-forwarder`
   - Verify email stored in S3 bucket

3. **Troubleshooting**
   - Check CloudWatch logs for Lambda errors
   - Verify S3 bucket contains received emails
   - Confirm SES rule set is active
   - Ensure domain shows "Verified" in SES

## Email Forwarding Configuration

### Supported Patterns

The `forwardMapping` object supports various email routing patterns:

```javascript
forwardMapping: {
  // Exact username match
  "info": ["destination@gmail.com"],
  
  // Wildcard patterns  
  "support.*": ["support-team@gmail.com"],
  
  // Domain catch-all
  "@yourdomain.com": ["admin@gmail.com"],
  
  // Subdomain handling
  "@www.yourdomain.com": ["www@gmail.com"],
  
  // Default fallback (catches all unmatched emails)
  "@": ["fallback@gmail.com"]
}
```

### Advanced Configuration Options

```javascript
const defaultConfig = {
  fromEmail: "lambda_forwarder@yourdomain.com",  // Must be verified in SES
  subjectPrefix: "[YourDomain] ",                // Optional email subject prefix
  emailBucket: "yourdomain-email-bucket",        // S3 bucket name
  emailKeyPrefix: "emailsPrefix/",               // S3 object prefix
  allowPlusSign: true,                           // Support email+tag@domain.com
  forwardMapping: { /* your rules */ }
};
```

## Monitoring and Maintenance

### CloudWatch Logs
- **Log group:** `/aws/lambda/yourdomain-email-forwarder`
- **Monitor for:** Processing steps, errors, forwarding success
- **Set up alerts** for Lambda errors or failures

### SES Metrics
- **Bounce rates:** Keep below 5%
- **Complaint rates:** Keep below 0.1%
- **Delivery statistics:** Monitor in SES console

### S3 Storage Management
- **Emails stored indefinitely** by default
- **Consider lifecycle policies** to delete old emails after 30-90 days
- **Average email size:** 10-50KB

## Security Best Practices

1. **Restrict S3 Access:** Bucket policy only allows SES and Lambda services
2. **Monitor Logs:** Set up CloudWatch alarms for errors
3. **Regular Audits:** Review forwarding rules periodically
4. **Email Verification:** Ensure sender addresses are verified in SES
5. **DKIM Authentication:** Keep DKIM enabled for better email reputation

## Cost Estimation

**Monthly costs for moderate usage (100 emails/month):**
- SES receiving: $0.10
- SES sending: $0.10  
- Lambda executions: $0.00 (free tier)
- S3 storage: $0.02
- **Total: ~$0.22/month**

## Troubleshooting

### Common Issues

**Domain Not Verifying:**
- Check DNS records are correctly added to Route 53
- Wait up to 72 hours for DNS propagation
- Verify DKIM CNAME records match SES requirements

**Emails Not Forwarding:**
- Check CloudWatch logs for Lambda errors
- Verify SES rule set is active
- Confirm S3 bucket policy allows SES writes
- Ensure sender email is verified in SES

**Lambda Execution Errors:**
- Verify IAM role has required permissions
- Check S3 bucket exists and is accessible
- Confirm Lambda function is in us-east-1 region
- Review function timeout and memory settings

**Forwarded Emails Going to Spam:**
- Ensure DKIM records are properly configured
- Add SPF record: `"v=spf1 include:amazonses.com ~all"`
- Consider configuring DMARC policy
- Monitor SES reputation metrics

### Support Resources

1. **AWS SES Documentation:** https://docs.aws.amazon.com/ses/
2. **Lambda Troubleshooting:** Check CloudWatch logs first
3. **DNS Issues:** Verify Route 53 records match SES requirements
4. **Email Deliverability:** Monitor SES sending statistics


## Next Steps

After successful setup:
1. **Test thoroughly** with various email addresses
2. **Set up monitoring** alerts for failures
3. **Document your email mappings** for team reference  
4. **Consider backup** Lambda function for redundancy
5. **Review costs** monthly and optimize as needed