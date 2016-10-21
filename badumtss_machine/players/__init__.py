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

"""MIDI player implementations."""

import logging

logger = logging.getLogger("players")

def player_factory(config, loop):
    """Create MIDI players from configuration, return the first one successfuly
    created.
    """
    for section in config:
        if section.startswith("jack:"):
            try:
                from .jack import JackPlayer
            except ImportError as err:
                logger.warning("[%s]: cannot load Jack Player: %s",
                               section, err)
                continue
            try:
                player = JackPlayer(config, section, loop)
            except Exception as err:
                logger.warning("[%s]: cannot load Jack Player: %s",
                               section, err)
                logger.debug("Exception:", exc_info=True)
                continue
            return player
        if section.startswith("fluidsynth:"):
            try:
                from .fluidsynth import FluidSynthPlayer
            except ImportError as err:
                logger.warning("[%s]: cannot load FluidSynth player: %s",
                               section, err)
                continue
            try:
                player = FluidSynthPlayer(config, section, loop)
            except Exception as err:
                logger.warning("[%s]: cannot load FluidSynth player: %s",
                               section, err)
                logger.debug("Exception:", exc_info=True)
                continue
            return player
    return None
