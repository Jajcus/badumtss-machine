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

"""Send MIDI notes to a Jack port or ports."""

import logging
import re

from functools import partial
from queue import Queue, Empty

import jack

from .base import RawMidiPlayer

logger = logging.getLogger("players.jack")
jack_logger = logging.getLogger("players.jack.jackd")

class JackPlayer(RawMidiPlayer):
    """Jack MIDI player.

    Sends MIDI notes to a Jack port or ports.
    """
    def __init__(self, config, section, main_loop):
        super().__init__(config, section, main_loop)
        target_ports_re = config[section].get("connect", ".*")
        if target_ports_re:
            self._target_ports_re = re.compile(target_ports_re)
        else:
            self._target_ports_re = None
        start_server = config[section].getboolean("start_server", False)
        self._active = 0
        self._queue = Queue()
        jack.set_error_function(partial(jack_logger.error, "%s"))
        jack.set_info_function(partial(jack_logger.info, "%s"))
        self._client = jack.Client("Badum-tss machine",
                                   no_start_server=not start_server)
        self._client.set_shutdown_callback(self._shutdown)
        self._client.set_port_registration_callback(self._port_registration)
        self._client.set_port_rename_callback(self._port_rename)
        self._client.set_xrun_callback(self._xrun)
        self._client.set_process_callback(self._process)
        self._port = None

    def start(self):
        """Activate the Jack client and connect to the target ports."""
        if not self._active:
            self._client.activate()
            self._port = self._client.midi_outports.register("midi_out")
            self._connect_ports()
        self._active += 1

    def stop(self):
        """Deactivate the Jack client and disconnect from the server."""
        self._active -= 1
        if self._active < 0:
            self._port = None
            self._client.deactivate()
            self._client.close()

    def _connect_ports(self):
        """Connect to available MIDI ports matching configured pattern."""
        if not self._target_ports_re:
            return
        for port in self._client.get_ports(is_midi=True, is_input=True):
            match = self._target_ports_re.match(port.name)
            if match:
                logger.info("Connecting to %r", port.name)
                self._port.connect(port)

    def _shutdown(self, status, reason):
        """Handle Jack shutdown."""
        logger.info("Jack is shutting down: %s, %s", status, reason)
        self.main_loop.call_soon_threadsafe(self.main_loop.stop)

    def _port_registration(self, port, register):
        """Handle Jack port registration notification."""
        logger.info("port %s: %r",
                          "registered" if register else "unregistered",
                          port)
        if not port.is_midi or not port.is_input:
            return
        if not self._target_ports_re or not self._port:
            return
        match = self._target_ports_re.match(port.name)
        if match:
            logger.info("Connecting to %r", port.name)
            self.main_loop.call_soon_threadsafe(self._port.connect, port)

    def _port_rename(self, port, old, new):
        """Handle Jack port rename notification."""
        logger.info("port renamed: %r '%s' -> '%s'",
                          port, old, new)

    def _xrun(self, delay):
        """Handle Jack XRUN notification."""
        logger.warning("XRUN, delay: %s microseconds", delay)

    def _process(self, frames):
        """Pass queued MIDI events to Jack."""
        if not self._port:
            return
        self._port.clear_buffer()
        while True:
            try:
                msg = self._queue.get(False)
            except Empty:
                break
            self._port.write_midi_event(0, msg)
            self._queue.task_done()

    def send(self, midi_bytes):
        """Send a MIDI message to the synthesizer."""
        self._queue.put(midi_bytes)
