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

"""Run fluidsynth process and feed it with MIDI events."""

import asyncio
import asyncio.subprocess
import locale
import logging
import os
import re
import signal

from .base import Player, PlayerLoadError
from .. import midi

logger = logging.getLogger("players.fluidsynth")
fs_logger = logging.getLogger("players.fluidsynth.fluidsynth")

class FluidSynthPlayer(Player):
    """FluidSynt MIDI player.

    Sends MIDI notes to a FluidSynth process.
    """
    def __init__(self, config, section, main_loop):
        self._encoding = locale.getpreferredencoding(False)
        self._subprocess = None
        self._supervisor = None
        super().__init__(config, section, main_loop)
        self._command = config[section].get("command", "fluidsynth")
        self._audio_driver = config[section].get("audio_driver", None)
        self._extra_options = config[section].get("extra_options", None)
        try:
            self._soundfont = config[section]["soundfont"]
        except KeyError:
            raise PlayerLoadError("SoundFont not provided")
        if not os.path.exists(self._soundfont):
            raise PlayerLoadError("SoundFont file %r does not exist",
                              self._soundfont)
        command = self._command.split()
        command.append("-n")
        if self._audio_driver:
            command += ["-a", self._audio_driver]
        if self._extra_options:
            command += self._extra_options.split(" ")
        command.append(self._soundfont)
        logger.debug("Starting %r", " ".join(command))
        create = asyncio.subprocess.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                loop=self.main_loop)

        # start it now, so constructor can fail if there is no fluidsynth
        task = self.main_loop.create_task(create)
        self._subprocess = self.main_loop.run_until_complete(task)

    def __del__(self):
        if self._subprocess or self._supervisor:
            self.stop()

    async def _supervise(self):
        """Process subprocess output and exit status."""
        if self._subprocess is None:
            return
        try:
            while True:
                line = await self._subprocess.stderr.readline()
                if not line:
                    break
                fs_logger.debug(line.rstrip().decode(self._encoding, "replace"))
            rc = await self._subprocess.wait()
            if rc > 0:
                logger.warning("%r exitted with status %r", self._command, rc)
            elif rc < 0 and rc not in (-signal.SIGTERM, -signal.SIGINT):
                logger.warning("%r killed by signal %r", self._command, -rc)
        finally:
            self._subprocess = None

    def start(self):
        """Start communicating with fluidsynth subprocess."""
        self._supervisor = self.main_loop.create_task(self._supervise())

    def stop(self):
        """Stop fluidsynth."""
        if self._subprocess:
            self._subprocess.terminate()
        if self._supervisor:
            if not self.main_loop.is_closed():
                self.main_loop.run_until_complete(self._supervisor)
            self._supervisor = None
        else:
            self._subprocess = None

    def _send(self, command):
        """Send command to fluidsynth."""
        if not self._subprocess:
            return
        command = command.encode(self._encoding, "replace")
        self._subprocess.stdin.write(command)

    def handle_message(self, msg):
        """Handle MIDI or control message."""
        if isinstance(msg, midi.NoteOn):
            self._send("noteon {} {} {}\n"
                       .format(msg.channel - 1, msg.note, msg.velocity))
        elif isinstance(msg, midi.NoteOff):
            self._send("noteoff {} {} {}\n"
                       .format(msg.channel - 1, msg.note, msg.velocity))
        else:
            logger.debug("Unsupported message: %r", msg)
