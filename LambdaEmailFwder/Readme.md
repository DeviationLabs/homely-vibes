Note: Can test on replit, here: https://replit.com/@AmitButala/Testing-my-lambda#index.js

Also: play with the test event definition, but if the message_id is too stale, may need to update with a new one from the S3 bucket.

Inspired by: https://gist.github.com/mylesboone/b6113f8dd74617d27f54e5d0b8598ff7 but with modifications

Supports:
* simpler config (just match user, not domain)
* wildcards in forwarder.
* improved debug.

For testing:
(a) test in repl.it
(b) deploy in lambda and use test event
(c) Production test via cloudwatch livetail
