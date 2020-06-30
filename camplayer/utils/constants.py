#!/usr/bin/python3

import os


class CONSTANTS(object):

    APPDATA_DIR             = str("%s/.camplayer/" % os.path.expanduser('~'))   # Application data directory
    RESOURCE_DIR_ICONS      = "../resources/icons/"                             # Resource directory for icons
    RESOURCE_DIR_BCKGRND    = "../resources/backgrounds/"                       # Resource directory for backgrounds
    DEMO_CONFIG_PATH        = "../examples/demo-config.ini"                     # Demo config path
    CONFIG_PATH             = str("%sconfig.ini" % APPDATA_DIR)                 # Default config path
    CACHE_DIR               = str("%scache/" % APPDATA_DIR)                     # Cache directory for images and stream details

    WINDOW_OFFSET           = 10000                                             # Offset for off screen (invisible) windows
    PLAYER_INITIALIZE_MS    = 2000                                              # Player max initializing time
    HW_DEC_MAX_WEIGTH       = 1920 * 1080 * 60                                  # PI hardware decoder limit (experimental)
    MAX_DECODER_STREAMS     = 16                                                # OMXplayer hard limit
    DBUS_TIMEOUT_MS         = 1000                                              # Timeout for dbus-send commands
    DBUS_RETRIES            = 5                                                 # Max dbus-send retries
    LOG_LINE_LEN            = 170                                               # Logger line length in characters
    PYTHON_VER_MIN          =  (3, 7)                                           # Minimum required Python version
    MIN_GPU_MEM             = 256                                               # Mininum required GPU memory split
    MAX_SCREENS             = 32
    MAX_WINDOWS             = 16
    KEY_TIMEOUT_MS          = 3000
    KEY_MULTIDIGIT_MS       = 1000
    VIRT_SCREEN_WIDTH       = 0
    VIRT_SCREEN_HEIGHT      = 0
    VIRT_SCREEN_OFFSET_X    = 0
    VIRT_SCREEN_OFFSET_Y    = 0
    ICON_OFFSET_X           = 60
    ICON_OFFSET_Y           = 60


class KEYCODE(object):
    """Linux keyboard scancodes"""

    KEY_D                   = 32
    KEY_Q                   = 16
    KEY_LEFT                = 105
    KEY_RIGHT               = 106
    KEY_UP                  = 103
    KEY_DOWN                = 108
    KEY_ESC                 = 1
    KEY_EXIT                = 174
    KEY_ENTER               = 28
    KEY_KPENTER             = 96
    KEY_SPACE               = 57

    KEY_NUM = {
    # Key = scancode, value = number

        # Numeric codes
        2: 1,
        3: 2,
        4: 3,
        5: 4,
        6: 5,
        7: 6,
        8: 7,
        9: 8,
        10: 9,
        11: 0,

        # Keypad codes
        79: 1,
        80: 2,
        81: 3,
        75: 4,
        76: 5,
        77: 6,
        71: 7,
        72: 8,
        73: 9,
        82: 0,
    }