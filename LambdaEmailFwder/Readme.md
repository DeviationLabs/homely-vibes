# AWS Lambda SES Email Forwarder

A modernized AWS Lambda function for forwarding emails using SES (Simple Email Service).

## Requirements

- **Node.js 22+** (ES Modules with latest AWS SDK v3)
- AWS Lambda runtime: `nodejs22.x`
- AWS SDK v3 (`@aws-sdk/client-s3`, `@aws-sdk/client-ses`)

## Features

- **ES6+ Modern JavaScript**: Uses ES modules, async/await, template literals
- **AWS SDK v3**: Latest AWS SDK with improved performance and tree-shaking
- **Flexible Email Mapping**: Supports user-based, domain-based, and regex pattern matching
- **Plus Sign Support**: Handles email aliases with plus signs (e.g., user+tag@domain.com)
- **Comprehensive Logging**: Structured logging for debugging and monitoring

## Installation

```bash
npm install
```

## Configuration

The email forwarding rules are defined in the `defaultConfig` object:

```javascript
const defaultConfig = {
  fromEmail: "lambda_forwarder@deviationlabs.com",
  subjectPrefix: "",
  emailBucket: "deviationlabs-email-bucket", 
  emailKeyPrefix: "emailsPrefix/",
  allowPlusSign: true,
  forwardMapping: {
    // Direct user mappings
    "abutala": ["deviationlabsinc@gmail.com"],
    
    // Domain mappings  
    "@deviationlabs.com": ["abutala+devlabs@gmail.com"],
    
    // Regex patterns
    "ab.*": ["deviationlabsinc+ab@gmail.com"],
    
    // Catch-all
    "@": ["deviationlabsinc+default@gmail.com"]
  }
};
```

## Testing

- **Replit**: Test online at https://replit.com/@AmitButala/Testing-my-lambda#index.js
- **Lambda Console**: Deploy and use test events (update message_id if S3 object is stale)
- **Production**: Monitor via CloudWatch Live Tail

## Deployment

1. Package the function with dependencies
2. Deploy to AWS Lambda with `nodejs22.x` runtime
3. Configure SES to trigger this Lambda function
4. Set up S3 bucket for email storage

## Credits

Inspired by [mylesboone's gist](https://gist.github.com/mylesboone/b6113f8dd74617d27f54e0d0b8598ff7) with modern JavaScript enhancements.