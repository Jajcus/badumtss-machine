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

from .base import PlayerLoadError, UnknownPlayerTypeError

logger = logging.getLogger("players")

def player_factory_single(config, section, loop):
    """Create MIDI player from a configuration section.

    Raise PlayerLoadError if something goes wrong,
    UnknownPlayerError if the section does not describe a known player type.
    """
    if section not in config:
        raise PlayerLoadError("No such config section: {!r}".format(section))

    if ":" in section:
        player_type, player_name = section.split(":", 1)
    else:
        player_type, player_name = section, "default"
    if player_type == "jack":
        try:
            from .jack import JackPlayer
        except ImportError as err:
            raise PlayerLoadError("[{}]: cannot load Jack player: {}"
                                  .format(section, err))
        return JackPlayer(config, section, loop)
    elif player_type == "fluidsynth":
        try:
            from .fluidsynth import FluidSynthPlayer
        except ImportError as err:
            raise PlayerLoadError("[{}]: cannot load FluidSynth player: {}"
                                  .format(section, err))
        return FluidSynthPlayer(config, section, loop)
    else:
        raise UnknownPlayerTypeError("[{}]: not a known player config"
                                     .format(section))

def player_factory(config, loop, section=None):
    """Create MIDI players from configuration, return the first one successfuly
    created.
    """
    if section:
        try:
            return player_factory_single(config, section, loop)
        except PlayerLoadError as err:
            logger.error("%s", err)
            return None
    for section in config:
        if config[section].getboolean("disabled", False):
            continue
        try:
            return player_factory_single(config, section, loop)
        except UnknownPlayerTypeError:
            continue
        except PlayerLoadError as err:
            logger.info("%s", err)
        except Exception as err:
            logger.warning("[%s]: cannot load event device handler: %s",
                           section, err)
            logger.debug("Exception:", exc_info=True)
    return None
