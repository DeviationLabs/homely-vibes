sample app for building an always on sentiment analysis app

There are 3 directories:
* aiy_hat/aiy_runner.py
-- This runs on a raspberry Pi0 with a google AIY hat, which is just what I had lying around.
-- This also needs the google raspberry image and some handholding on tokens.
-- In dev mode tokens will expire every 7 days, and then need to be purged from ~/.cache/voice_recognition/assistant-config.json
-- Also note that you may need to hack auth_helpers.py to get the callback url for authentication.

* app/main.py
-- This is an ASGI fastapi service to deal with all the rest of the heavy lifting happening in a webapp.
-- We initially tested the webapp locally, but now we'll deploy it using AWS App runner. Cool deal!
-- Note that app runner is absolute balls. python3.11 is missing uvicorn. Also will not install fastapi.
-- other env is python8, and has issues with old versions.

launch for testing as either:
$ python3 -m app.main
$ uvicorn app.main:app --reload --port 8080 --host 0.0.0.0 --log-level info

* fe/streamlit_app.py
-- simple sweet front end for testing with the ASGI.

Can be locally tested with:
$ streamlit run fe/streamlit_app.py

Once we did the deploy, we used vanity domain names for everything, but this is not needed.
