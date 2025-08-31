import { S3Client, CopyObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3';
import { SESClient, SendRawEmailCommand } from '@aws-sdk/client-ses';

console.log("AWS Lambda SES Forwarder // @arithmetic // Version 5.0.0");

// Configure the S3 bucket and key prefix for stored raw emails, and the
// mapping of email addresses to forward from and to.
//
// Expected keys/values:
//
// - fromEmail: Forwarded emails will come from this verified address
//
// - subjectPrefix: Forwarded emails subject will contain this prefix
//
// - emailBucket: S3 bucket name where SES stores emails.
//
// - emailKeyPrefix: S3 key name prefix where SES stores email. Include the
//   trailing slash.
//
// - allowPlusSign: Enables support for plus sign suffixes on email addresses.
//   If set to `true`, the username/mailbox part of an email address is parsed
//   to remove anything after a plus sign. For example, an email sent to
//   `example+test@example.com` would be treated as if it was sent to
//   `example@example.com`.
//
// - forwardMapping: Object where the key is the lowercase email address from
//   which to forward and the value is an array of email addresses to which to
//   send the message.
//
//   To match all email addresses on a domain, use a key without the name part
//   of an email address before the "at" symbol (i.e. `@example.com`).
//
//   To match a mailbox name on all domains, use a key without the "at" symbol
//   and domain part of an email address (i.e. `info`).
//
//   To match all email addresses matching no other mapping, use "@" as a key.
const defaultConfig = {
  fromEmail: "lambda_forwarder@deviationlabs.com",
  subjectPrefix: "",
  emailBucket: "deviationlabs-email-bucket",
  emailKeyPrefix: "emailsPrefix/",
  allowPlusSign: true,
  forwardMapping: {

   //strict ...
    abutala: ["deviationlabsinc@gmail.com"],
    amitbutala: ["abutala+strict@gmail.com"], // Note: abutala@gmail...
    devlabs: ["deviationlabsinc+strict@gmail.com"],
    eden: ["eden.foscam@gmail.com"],
    info: ["deviationlabsinc+info@gmail.com"],
    mamata: ["mamatadesai@yahoo.com"],
    rb: ["rianbutala@gmail.com"],
    rian: ["rianbutala@gmail.com"],
    rianbutala: ["rianbutala@gmail.com"],

    // exceptions ...
    "ab.*": ["deviationlabsinc+ab@gmail.com"],
    "rb.*": ["rianbutala+rb@gmail.com"],
    "rian.*": ["rianbutala+default@gmail.com"],
    "@deviationlabs.com": ["abutala+devlabs@gmail.com"],
    "@www.deviationlabs.com": ["deviationlabsinc+www@gmail.com"],
    "@mail.deviationlabs.com": ["deviationlabsinc+mail@gmail.com"],
    "@": ["deviationlabsinc+default@gmail.com"],
  },
};

/**
 * Parses the SES event record provided for the `mail` and `recipients` data.
 *
 * @param {object} data - Data bundle with context, email, etc.
 *
 * @return {object} - Promise resolved with data.
 */
export const parseEvent = async (data) => {
  // Validate characteristics of a SES event record.
  if (!data.event ||
      !data.event.hasOwnProperty('Records') ||
      data.event.Records.length !== 1 ||
      !data.event.Records[0].hasOwnProperty('eventSource') ||
      data.event.Records[0].eventSource !== 'aws:ses' ||
      data.event.Records[0].eventVersion !== '1.0') {
    data.log({
      message: "parseEvent() received invalid SES message:",
      level: "error", event: JSON.stringify(data.event)
    });
    return Promise.reject(new Error('Error: Received invalid SES message.'));
  }

  data.email = data.event.Records[0].ses.mail;
  data.recipients = data.event.Records[0].ses.receipt.recipients;
  return Promise.resolve(data);
};

/**
 * Helper function to return null if no pattern matches
 */
const findMatchingPattern = (inputString, patterns) => {
  for (const pattern of patterns) {
    const regex = new RegExp(`^${pattern}$`); // Fixed template literal
    if (regex.test(inputString)) {
      return pattern;
    }
  }
  return null;
};

/**
 * Transforms the original recipients to the desired forwarded destinations.
 *
 * @param {object} data - Data bundle with context, email, etc.
 *
 * @return {object} - Promise resolved with data.
 */
export const transformRecipients = async (data) => {
  let newRecipients = [];
  data.originalRecipients = data.recipients;
  data.recipients.forEach((origEmail) => {
    console.log("Orig Email:" + origEmail);
    var origEmailKey = origEmail.toLowerCase();

    if (data.config.allowPlusSign) {
      origEmailKey = origEmailKey.replace(/\+.*?@/, '@');
    }
    if (data.config.forwardMapping.hasOwnProperty(origEmailKey)) {
      newRecipients = newRecipients.concat(
        data.config.forwardMapping[origEmailKey]);
      data.originalRecipient = origEmail;
    } else {
      let origEmailDomain;
      let origEmailUser;
      const pos = origEmailKey.lastIndexOf("@");
      if (pos === -1) {
        origEmailUser = origEmailKey;
      } else {
        origEmailDomain = origEmailKey.slice(pos);
        origEmailUser = origEmailKey.slice(0, pos);
      }
      console.log("Orig Email Domain:" + origEmailDomain);
      console.log("Orig Email User:" + origEmailUser);

      // First match on user chunk
      // Then user regex
      // Then on domain chunk
      // Else default rule (if specified in data.config)
      const matchingKey = findMatchingPattern(
        origEmailUser,
        Object.keys(data.config.forwardMapping),
      );
      if (origEmailUser && data.config.forwardMapping.hasOwnProperty(origEmailUser)) {
        newRecipients = newRecipients.concat(
          data.config.forwardMapping[origEmailUser],
        );
        data.originalRecipient = origEmail;
      } else if (origEmailUser && matchingKey) {
        newRecipients = newRecipients.concat(data.config.forwardMapping[matchingKey]);
      } else if (
        origEmailDomain &&
        data.config.forwardMapping.hasOwnProperty(origEmailDomain)
      ) {
        newRecipients = newRecipients.concat(
          data.config.forwardMapping[origEmailDomain],
        );
        data.originalRecipient = origEmail;
      } else if (data.config.forwardMapping.hasOwnProperty("@")) {
        newRecipients = newRecipients.concat(data.config.forwardMapping["@"]);
        data.originalRecipient = origEmail;
      }

      console.log("New recipients:" + newRecipients);
    }
  });

  if (!newRecipients.length) {
    data.log({
      message: "Finishing process. No new recipients found for " +
        "original destinations: " + data.originalRecipients.join(", "),
      level: "info"
    });
    return data.callback();
  }

  data.recipients = newRecipients;
  return Promise.resolve(data);
};

/**
 * Fetches the message data from S3.
 *
 * @param {object} data - Data bundle with context, email, etc.
 *
 * @return {object} - Promise resolved with data.
 */
export const fetchMessage = async (data) => {
  // Copying email object to ensure read permission
  data.log({
    level: "info",
    message: "Fetching email at s3://" + data.config.emailBucket + '/' +
      data.config.emailKeyPrefix + data.email.messageId
  });
  try {
    // Copy email object to ensure read permission
    await data.s3.send(new CopyObjectCommand({
      Bucket: data.config.emailBucket,
      CopySource: `${data.config.emailBucket}/${data.config.emailKeyPrefix}${data.email.messageId}`,
      Key: `${data.config.emailKeyPrefix}${data.email.messageId}`,
      ACL: 'private',
      ContentType: 'text/plain',
      StorageClass: 'STANDARD'
    }));

    // Load the raw email from S3
    const result = await data.s3.send(new GetObjectCommand({
      Bucket: data.config.emailBucket,
      Key: `${data.config.emailKeyPrefix}${data.email.messageId}`
    }));
    
    data.emailData = await result.Body.transformToString();
    return data;
  } catch (err) {
    data.log({
      level: "error",
      message: "S3 operation failed:",
      error: err,
      stack: err.stack
    });
    throw new Error("Error: Could not fetch email from S3.");
  }
};

/**
 * Processes the message data, making updates to recipients and other headers
 * before forwarding message.
 *
 * @param {object} data - Data bundle with context, email, etc.
 *
 * @return {object} - Promise resolved with data.
 */
export const processMessage = async (data) => {
  const emailMatch = data.emailData.match(/^((?:.+\r?\n)*)(\r?\n(?:.*\s+)*)/m);
  let header = emailMatch?.[1] ?? data.emailData;
  const body = emailMatch?.[2] ?? '';

  // Add "Reply-To:" with the "From" address if it doesn't already exist
  if (!/^reply-to:[\t ]?/mi.test(header)) {
    const fromMatch = header.match(/^from:[\t ]?(.*(?:\r?\n\s+.*)*\r?\n)/mi);
    const from = fromMatch?.[1] ?? '';
    if (from) {
      header = header + 'Reply-To: ' + from;
      data.log({
        level: "info",
        message: "Added Reply-To address of: " + from
      });
    } else {
      data.log({
        level: "info",
        message: "Reply-To address not added because From address was not " +
          "properly extracted."
      });
    }
  }

  // SES does not allow sending messages from an unverified address,
  // so replace the message's "From:" header with the original
  // recipient (which is a verified domain)
  header = header.replace(
    /^from:[\t ]?(.*(?:\r?\n\s+.*)*)/mgi,
    (_, from) => {
      if (data.config.fromEmail) {
        return `From: ${from.replace(/<(.*)>/, '').trim()} <${data.config.fromEmail}>`;
      } else {
        return `From: ${from.replace('<', 'at ').replace('>', '')} <${data.originalRecipient}>`;
      }
    });

  // Add a prefix to the Subject
  if (data.config.subjectPrefix) {
    header = header.replace(
      /^subject:[\t ]?(.*)/mgi,
      (_, subject) => `Subject: ${data.config.subjectPrefix}${subject}`
    );
  }

  // Replace original 'To' header with a manually defined one
  if (data.config.toEmail) {
    header = header.replace(/^to:[\t ]?(.*)/mgi, () => 'To: ' + data.config.toEmail);
  }

  // Remove the Return-Path header.
  header = header.replace(/^return-path:[\t ]?(.*)\r?\n/mgi, '');

  // Remove Sender header.
  header = header.replace(/^sender:[\t ]?(.*)\r?\n/mgi, '');

  // Remove Message-ID header.
  header = header.replace(/^message-id:[\t ]?(.*)\r?\n/mgi, '');

  // Remove all DKIM-Signature headers to prevent triggering an
  // "InvalidParameterValue: Duplicate header 'DKIM-Signature'" error.
  // These signatures will likely be invalid anyways, since the From
  // header was modified.
  header = header.replace(/^dkim-signature:[\t ]?.*\r?\n(\s+.*\r?\n)*/mgi, '');

  data.emailData = header + body;
  return Promise.resolve(data);
};

/**
 * Send email using the SES sendRawEmail command.
 *
 * @param {object} data - Data bundle with context, email, etc.
 *
 * @return {object} - Promise resolved with data.
 */
export const sendMessage = async (data) => {
  const params = {
    Destinations: data.recipients,
    Source: data.originalRecipient,
    RawMessage: {
      Data: Buffer.from(data.emailData)
    }
  };
  data.log({
    level: "info",
    message: "sendMessage: Sending email via SES. Original recipients: " +
      data.originalRecipients.join(", ") + ". Transformed recipients: " +
      data.recipients.join(", ") + "."
  });
  try {
    const result = await data.ses.send(new SendRawEmailCommand(params));
    data.log({
      level: "info",
      message: "SendRawEmailCommand() successful.",
      result: result
    });
    return data;
  } catch (err) {
    data.log({
      level: "error",
      message: "SendRawEmailCommand() returned error.",
      error: err,
      stack: err.stack
    });
    throw new Error('Error: Email sending failed.');
  }
};

/**
 * Handler function to be invoked by AWS Lambda with an inbound SES email as
 * the event.
 *
 * @param {object} event - Lambda event from inbound email received by AWS SES.
 * @param {object} context - Lambda context object.
 * @param {object} callback - Lambda callback object.
 * @param {object} overrides - Overrides for the default data, including the
 * configuration, SES object, and S3 object.
 */
export const handler = async (event, context, callback, overrides) => {
  const steps = overrides?.steps ?? [
    parseEvent,
    transformRecipients,
    fetchMessage,
    processMessage,
    sendMessage
  ];
  
  const data = {
    event,
    callback,
    context,
    config: overrides?.config ?? defaultConfig,
    log: overrides?.log ?? console.log,
    ses: overrides?.ses ?? new SESClient(),
    s3: overrides?.s3 ?? new S3Client({ signatureVersion: 'v4' })
  };

  try {
    let result = data;
    for (const step of steps) {
      if (typeof step !== 'function') {
        throw new Error(`Invalid step: ${step}`);
      }
      result = await step(result);
    }
    
    data.log({
      level: "info",
      message: "Process finished successfully."
    });
    return callback?.() ?? result;
  } catch (err) {
    data.log({
      level: "error",
      message: `Step returned error: ${err.message}`,
      error: err,
      stack: err.stack
    });
    if (callback) {
      return callback(new Error("Error: Step returned error."));
    }
    throw err;
  }
};

// Promise.series is no longer needed - replaced with async/await in handler

