#!/usr/bin/env python3
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Activates the Google Assistant with either a hotword or a button press, using the
Google Assistant Library.

The Google Assistant Library has direct access to the audio API, so this Python
code doesn't need to record audio.

.. note:

    Hotword detection (such as "Okay Google") is supported only with Raspberry Pi 2/3.
    If you're using a Pi Zero, this code works but you must press the button to activate
    the Google Assistant.
"""

import logging
import sys
import threading

from google.assistant.library.event import EventType

# from aiy.assistant import auth_helpers
from . import auth_helpers
from aiy.assistant.library import Assistant
from aiy.board import Board, Led
from aiy.voice import tts

# import requests module
import requests
from urllib.parse import urljoin

# BASE_URL = "https://aiybackend.deviationlabs.com:8080/api/v1/"
BASE_URL = "https://aiybackend.deviationlabs.com/api/v1/"  # APB: why is this not 8080? Dunno? AWS App runner sucks!

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# create formatter
# logging.basicConfig()
# logging.getLogger().setLevel(logging.DEBUG)
# formatter = logging.Formatter("%(asctime)s;%(levelname)s;%(message)s",
#                              "%Y-%m-%d %H:%M:%S")


class MyAssistant:
    """An assistant that runs in the background.

    The Google Assistant Library event loop blocks the running thread entirely.
    To support the button trigger, we need to run the event loop in a separate
    thread. Otherwise, the on_button_pressed() method will never get a chance to
    be invoked.
    """

    def __init__(self):
        logging.warning("Initializing...")
        self._task = threading.Thread(target=self._run_task)
        self._can_start_conversation = False
        self._assistant = None
        self._board = Board()
        self._board.button.when_pressed = self._on_button_pressed

    def start(self):
        """
        Starts the assistant event loop and begins processing events.
        """
        self._task.start()

    def _run_task(self):
        credentials = auth_helpers.get_assistant_credentials()
        with Assistant(credentials) as assistant:
            self._assistant = assistant
            for event in assistant.start():
                self._process_event(event)

    def _process_event(self, event):
        logging.info(event)
        if event.type == EventType.ON_START_FINISHED:
            self._board.led.status = Led.BEACON_DARK  # Ready.
            self._can_start_conversation = True
            # Start the voicehat button trigger.
            logging.info(
                'Say "OK, Google" or press the button, then speak. Press Ctrl+C to quit...'
            )

        elif event.type == EventType.ON_CONVERSATION_TURN_STARTED:
            self._can_start_conversation = False
            self._board.led.state = Led.ON  # Listening.

        elif event.type == EventType.ON_END_OF_UTTERANCE:
            #            self._board.led.state = Led.PULSE_QUICK  # Thinking.
            self._board.led.state = Led.BEACON_DARK

        elif (
            event.type == EventType.ON_CONVERSATION_TURN_FINISHED
            or event.type == EventType.ON_CONVERSATION_TURN_TIMEOUT
            or event.type == EventType.ON_NO_RESPONSE
        ):
            self._board.led.state = Led.BEACON_DARK  # Ready.
            self._can_start_conversation = True
        #            self._summarize()

        elif event.type in [
            EventType.ON_RECOGNIZING_SPEECH_FINISHED,
            EventType.ON_RENDER_RESPONSE,
            EventType.ON_CONVERSATION_TURN_FINISHED,
        ]:
            self._board.led.state = Led.BEACON_DARK  # Ready.
            text = event._args.get("text")
            logging.info(f"After {event.type}, got: {text}")
            if text and text in ["summarize"]:
                self._summarize(text)
            elif text:
                self._index_text(text)
            else:
                self._summarize(text)

        elif event.type == EventType.ON_ASSISTANT_ERROR and event.args and event.args["is_fatal"]:
            sys.exit(1)

    def _on_button_pressed(self):
        # Check if we can start a conversation. 'self._can_start_conversation'
        # is False when either:
        # 1. The assistant library is not yet ready; OR
        # 2. The assistant library is already in a conversation.

        # self.button.wait_for_release() : APB can do fancier stuff this way but will need to add a timeout.

        if self._can_start_conversation:
            self._assistant.start_conversation()

    def _index_text(self, text):
        try:
            logging.info("Attempting to index ...")
            response = requests.post(
                urljoin(BASE_URL, "index"),
                headers={"auth": "validated_user"},
                json=dict(text=text),
            )
            print(response)
        except Exception as e:
            logging.warning(f"Caught and ignored the following exception {e}")

    def _summarize(self, text):
        try:
            logging.info("Attempting to summarize ...")
            response = requests.post(
                urljoin(BASE_URL, "summarize"),
                headers={"auth": "validated_user"},
                json=dict(summary_question=text),
            )
            print(response)
            tts.say(response.message)
        except Exception as e:
            logging.warning(f"Caught and ignored the following exception {e}")


class MyAuth(requests.auth.AuthBase):
    # unused: APB 03/07/24
    def __call__(self, r):
        # Implement my authentication
        return "validated_user"


def main():
    MyAssistant().start()


if __name__ == "__main__":
    main()
