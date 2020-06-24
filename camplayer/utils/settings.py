#!/usr/bin/python3

import os
import sys

from enum import IntEnum
from enum import unique
from configparser import ConfigParser

from . import logger
from . import constants


@unique
class LAYOUT(IntEnum):
    _1X1                = 1
    _2X2                = 4
    _3X3                = 9
    _1P5                = 6
    _1P7                = 8
    _3P4                = 7
    _2P8                = 10
    _1P12               = 13
    _4X4                = 16


@unique
class CHANGEOVER(IntEnum):
    NORMAL              = 0     # Stop streams of current screen, then start streams of new screen.
                                # -> less bandwidth/active players but slow...
    PREBUFFER           = 1     # Start streams of new screen in background to speedup changeover.
                                # -> Uses more resources.
    PREBUFFER_SMOOTH    = 2     # Similar as previous method but without the split second black screen.
                                # -> Uses the most resources.


@unique
class BACKGROUND(IntEnum):
    HIDE_FRAMEBUFFER    = 0     # No background and hide framebuffer
    STATIC              = 1     # Grid background (1 static image)
    DYNAMIC             = 2     # Grid background (image depending on active screen)
    OFF                 = 3


@unique
class STREAMQUALITY(IntEnum):
    LOW                 = 0     # Always use the lowest quality stream
    AUTO                = 1     # Auto select the stream quality
    HIGH                = 2     # Always use highest (sensible) quality stream


@unique
class HEVCMODE(IntEnum):
    OFF                = 0     # Disable hevc decoding
    AUTO               = 1     # Auto select based on pi model
    FHD                = 2     # Enable hevc decoding up to FHD/1080p
    UHD                = 3     # Enable hevc decoding up to UHD/4k

@unique
class AUDIOMODE(IntEnum):
    OFF                = 0     # Disable audio
    FULLSCREEN         = 1     # On for fullscreen playback


class CONFIG(object):

    _LOG_NAME = "Config"

    # Filled with overwritten advanced settings for logging purpose
    advanced_overwritten = []

    @classmethod
    def load(cls):
        """Load config file from disk"""

        cls.config = ConfigParser()

        if not os.path.isfile(constants.CONSTANTS.CONFIG_PATH):
            logger.log_message(cls._LOG_NAME, logger.LOGLEVEL.ERROR,
                               "Settings file '%s' not found!" % constants.CONSTANTS.CONFIG_PATH)
            sys.exit("No configuration file found")

        # Read config file
        cls.config.read(constants.CONSTANTS.CONFIG_PATH)

        # Advanced settings, overridable in config file
        cls.LOG_LEVEL               = cls.read_setting_default_int("ADVANCED", "loglevel",           logger.LOGLEVEL.DEBUG)
        cls.SCREEN_WIDTH            = cls.read_setting_default_int("ADVANCED", "screenwidth",        0)                         # 0 = Auto detect
        cls.SCREEN_HEIGHT           = cls.read_setting_default_int("ADVANCED", "screenheight",       0)                         # 0 = Auto detect
        cls.BUFFERTIME_MS           = cls.read_setting_default_int("ADVANCED", "buffertime",         500)
        cls.HARDWARE_CHECK          = cls.read_setting_default_int("ADVANCED", "hardwarecheck",      1)
        cls.CHANGE_OVER             = cls.read_setting_default_int("ADVANCED", "screenchangeover",   CHANGEOVER.PREBUFFER)
        cls.SHOWTIME                = cls.read_setting_default_int("ADVANCED", "showtime",           10)
        cls.BACKGROUND_MODE         = cls.read_setting_default_int("ADVANCED", "backgroundmode",     BACKGROUND.DYNAMIC)
        cls.ENABLE_ICONS            = cls.read_setting_default_int("ADVANCED", "icons",              1)
        cls.STREAM_WATCHDOG_SEC     = cls.read_setting_default_int("ADVANCED", "streamwatchdog",     15)
        cls.PLAYTIMEOUT_SEC         = cls.read_setting_default_int("ADVANCED", "playtimeout",        10)
        cls.STREAM_QUALITY          = cls.read_setting_default_int("ADVANCED", "streamquality",      STREAMQUALITY.AUTO)
        cls.REFRESHTIME_MINUTES     = cls.read_setting_default_int("ADVANCED", "refreshtime",        60)
        cls.HEVC_MODE               = cls.read_setting_default_int("ADVANCED", "enablehevc",         HEVCMODE.AUTO)
        cls.AUDIO_MODE              = cls.read_setting_default_int("ADVANCED", "enableaudio",        AUDIOMODE.OFF)
        cls.AUDIO_VOLUME            = cls.read_setting_default_int("ADVANCED", "audiovolume",        100)                       # 100%
        cls.SCREEN_DOWNSCALE        = cls.read_setting_default_int("ADVANCED", "screendownscale",    0)                         # 0%
        cls.VIDEO_OSD               = cls.read_setting_default_int("ADVANCED", "enablevideoosd",     0)                         # Channel name overlay on video

    @classmethod
    def get_settings_for_section(cls, section):
        """Get all settings in a specific section of the config file"""

        return cls.config.items(section)

    @classmethod
    def read_setting(cls, section, setting):
        """Read setting from config file?"""

        return cls.read_setting_default(section, setting, None)

    @classmethod
    def has_setting(cls, section, setting):
        """Setting present in config file?"""

        if not (cls.config.has_section(section)):
            return False

        return cls.config.has_option(section, setting)

    @classmethod
    def has_section(cls, section):
        """Section present in config file?"""

        return cls.config.has_section(section)

    @classmethod
    def read_setting_default(cls, section, setting, default):
        """
        Read setting from configfile.
        Returns default if setting not present.
        """

        if not (cls.config.has_section(section)):
            return default

        if not (cls.config.has_option(section, str(setting))):
            return default

        value = cls.config.get(section, setting)

        return value

    @classmethod
    def read_setting_default_int(cls, section, setting, default):
        """
        Read integer setting from configfile.
        Returns default if setting not present.
        """

        try:
            config_value = int(cls.read_setting_default(section, setting, default))

            # Save non default advanced settings for logging purpose
            if section == "ADVANCED" and config_value != default:
                cls.advanced_overwritten.append([setting, config_value])

            return config_value

        except ValueError:
            logger.log_message(cls._LOG_NAME, logger.LOGLEVEL.ERROR,
                               "failed to parse integer value from setting '%s', "
                               "using the default" % setting)

            return default
