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

import argparse
import asyncio
import locale
import logging
import logging.config
import os
import signal
import sys

from configparser import ConfigParser, ExtendedInterpolation

from .players import player_factory
from .input import input_devices_generator
from .wizard import keymap_wizard
from . import midi

logger = logging.getLogger()

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGGING_CONFIG = os.path.join(PKG_DIR, "logging.conf")

INTRO_NOTES = [0, 38, 38, 0, 49]

async def play_intro(player):
    for note in INTRO_NOTES:
        sys.stdout.flush()
        if note:
            msg = midi.NoteOn(10, note, 127)
            player.handle_message(msg)
        await asyncio.sleep(0.2)

async def route_messages(input_device, player):
    async for msg in input_device:
        logger.debug("msg: %r", msg)
        if isinstance(msg, midi.MidiMessage):
            player.handle_message(msg)
        else:
            logger.warning("Unknown input: %r", msg)

def command_args():
    parser = argparse.ArgumentParser(
            description="Play MIDI notes with any input device",
            )
    parser.add_argument("--debug", dest="log_level", action="store_const",
                        const=logging.DEBUG,
                        help="Show debugging messages")
    parser.add_argument("--quiet", dest="log_level", action="store_const",
                        const=logging.ERROR,
                        help="Show only error messages")
    parser.add_argument("--logging-config", metavar="FILENAME", nargs=1,
                        default=DEFAULT_LOGGING_CONFIG,
                        help="Alternative logging configuration")
    parser.add_argument("--player", "-p", metavar="SECTION",
                        help="Select specific player from config file")
    parser.add_argument("--input-device", "-i", metavar="SECTION",
                        help="Select specific input configuration from config file")
    parser.add_argument("--keymap-wizard", "-w", metavar="KEYMAP_FILENAME",
                        nargs="?", const="newkeymap.conf",
                        help="Interactive keymap configurator")
    args = parser.parse_args()
    logging.config.fileConfig(args.logging_config,
                              disable_existing_loggers=False)
    if args.log_level is not None:
        logging.getLogger().setLevel(args.log_level)
    return args

def play_input(args, loop, input_devices, player):
    """Play incoming input on the MIDI player."""
    routers = []
    try:
        loop.run_until_complete(play_intro(player))
        if not input_devices:
            logger.error("No input device found, exiting")
            return
        for input_device in input_devices:
            router = loop.create_task(route_messages(input_device, player))
            routers.append(router)
            input_device.start()
        loop.run_forever()
    finally:
        for router in routers:
            router.cancel()
            try:
                loop.run_until_complete(router)
            except asyncio.CancelledError:
                pass

def main():
    locale.setlocale(locale.LC_ALL, '')
    args = command_args()
    config = ConfigParser(interpolation=ExtendedInterpolation(),
                          default_section="defaults")
    config.add_section("paths")
    config["paths"] = { "pkgdir": PKG_DIR }
    config.read("badumtss.conf")

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, loop.stop)
        loop.add_signal_handler(signal.SIGTERM, loop.stop)

        player = player_factory(config, loop, section=args.player)
        if not player:
            logger.error("No MIDI player available.")
            if not args.keymap_wizard:
                return

        input_devices = list(input_devices_generator(config,
                                                     loop,
                                                     section=args.input_device))
        player.start()
        try:
            if args.keymap_wizard:
                keymap_wizard(args, loop, input_devices, player)
            else:
                play_input(args, loop, input_devices, player)
        finally:
            for input_device in input_devices:
                input_device.stop()
            player.stop()
    finally:
        loop.close()

if __name__ == "__main__":
    main()
