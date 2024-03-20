sample app for building an always on sentiment analysis app

The first function runs on a raspbery Pi0 with a google AIY hat. This is just what I had lying around.

The rest is a uvicorn service to deal with all the rest of the heavy lifting happening in a webapp.

We initially tested the webapp locally, but now we'll deploy it using AWS App runner. Cool deal!

launch for testing as either:

* python3 -m app.main
* uvicorn app.main:app --reload --port 8080 --host 0.0.0.0 --log-level info

