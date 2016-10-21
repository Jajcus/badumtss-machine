#!/usr/bin/python3

# Copyright (c) 2016, Jacek Konieczny
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import logging
import asyncio
import signal
import sys

from configparser import ConfigParser, ExtendedInterpolation

from .players import player_factory
from .input import input_devices_generator

logger = logging.getLogger()

INTRO_NOTES = [38, 38, 0, 49]

async def play_intro(player):
    for note in INTRO_NOTES:
        sys.stdout.flush()
        if note:
            player.note_on(10, note, 127)
        await asyncio.sleep(0.2)

def setup_signals(loop):
    def handler(signum, frame):
        loop.call_soon_threadsafe(loop.stop)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

def main():
    logging.basicConfig(level=logging.DEBUG)
    config = ConfigParser(interpolation=ExtendedInterpolation())
    config['DEFAULT'] = {
                         "input_device": ".*",
                         }
    config.read("badumtss.conf")

    loop = asyncio.get_event_loop()
    setup_signals(loop)

    player = player_factory(config, loop)
    if not player:
        logger.error("No MIDI player available.")
        return

    input_devices = list(input_devices_generator(config, loop, player))

    player.start()
    try:
        loop.run_until_complete(play_intro(player))
        if not input_devices:
            logger.error("No input device found, exiting")
            return
        for input_device in input_devices:
            input_device.start()
        loop.run_forever()
    finally:
        for input_device in input_devices:
            input_device.stop()
        player.stop()
        loop.close()

if __name__ == "__main__":
    main()
