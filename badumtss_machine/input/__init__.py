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

"""Input device interface."""

import logging

from importlib import import_module

from .base import InputDeviceLoadError, UnknownDeviceTypeError

logger = logging.getLogger("input")

DRIVERS = {"evdev", "terminal", "gtk"}

loaded_drivers = {}

def probe_input_drivers(config):
    """Import input driver modules and perform early initializations."""
    for section in config:
        if config[section].getboolean("disabled", False):
            continue
        if ":" in section:
            driver_name = section.split(":", 1)[0]
        else:
            driver_name = section
        if driver_name not in DRIVERS:
            continue
        if driver_name in loaded_drivers:
            continue
        try:
            if "." not in driver_name:
                module = import_module("." + driver_name, __package__)
            else:
                module = import_module(driver_name)
        except ImportError as err:
            logger.info("[%s]: could not load input driver: %s", section, err)
            loaded_drivers[driver_name] = None
            continue
        if hasattr(module, "initialize_input_driver"):
            try:
                module.initialize_input_driver(config)
            except InputDeviceLoadError as err:
                logger.info("[%s]: could not initialize input driver: %s",
                            section, err)
                loaded_drivers[driver_name] = None
                continue
            except Exception as err:
                logger.warning("[%s]: could not initialize input driver: %s",
                               section, err, exc_info=True)
                loaded_drivers[driver_name] = None
                continue
        loaded_drivers[driver_name] = module

def input_devices_generator_single(config, section, loop):
    """Create input device handlers from a single configuration section.

    Yield created objects.

    Raise InputDeviceLoadError if something goes wrong,
    UnknownDeviceTypeError if the section does not describe a known device type.
    """
    if section not in config:
        raise InputDeviceLoadError("No such config section: {!r}"
                                   .format(section))

    if ":" in section:
        driver_name, dev_name = section.split(":", 1)
    else:
        driver_name, dev_name = section, "default"
    if driver_name not in DRIVERS:
        raise UnknownDeviceTypeError("[{}]: not a known input device config"
                                     .format(section))
    module = loaded_drivers.get(driver_name)
    if not module:
        raise InputDeviceLoadError("[{}]: coult load event device handler"
                                   .format(section))
    yield from module.input_device_factory(config, section, loop)

def input_devices_generator(config, loop, section=None):
    """Create input device handlers from configuration, yield created objects.
    """
    if section:
        try:
            yield from input_devices_generator_single(config,
                                                      section,
                                                      loop)
        except InputDeviceLoadError as err:
            logger.info("%s", err)
            return
    for section in config:
        if config[section].getboolean("disabled", False):
            continue
        try:
            yield from input_devices_generator_single(config,
                                                      section,
                                                      loop)
        except UnknownDeviceTypeError:
            continue
        except InputDeviceLoadError as err:
            logger.info("%s", err)
        except Exception as err:
            logger.warning("[%s]: cannot load event device handler: %s",
                           section, err)
            logger.debug("Exception:", exc_info=True)
