#!/usr/bin/python3

import sys
import os
import time
import platform
import signal

from utils.logger import LOG
from utils.settings import CONFIG, HEVCMODE, BACKGROUND
from utils.constants import CONSTANTS, KEYCODE
from utils.globals import GLOBALS
from utils.inputhandler import InputMonitor
from utils import utils

from backgroundgen import BackGroundManager, BackGround
from screenmanager import ScreenManager
from screenmanager import Action

running = True

_LOG_NAME = "Main"
__version__ = "1.0.0b5"


def signal_handler(signum, frame):
    """SIGTERM/SIGINT callback, terminate our application..."""

    global running
    running = False


def clear_cache():
    """Clear our cache directory"""

    if os.path.isdir(CONSTANTS.CACHE_DIR):
        for filename in os.listdir(CONSTANTS.CACHE_DIR):
            os.remove(os.path.join(CONSTANTS.CACHE_DIR, filename))


def main():
    """Application entry point"""

    global running

    num_array = []
    last_added = time.monotonic()
    ignore_quit = False

    if not platform.system() == "Linux":
        sys.exit("'%s' OS not supported!" % platform.system())

    if os.geteuid() == 0:
        sys.exit("Camplayer is not supposed to be run as root!")

    GLOBALS.PYTHON_VER = sys.version_info
    if GLOBALS.PYTHON_VER < CONSTANTS.PYTHON_VER_MIN:
        sys.exit("Python version '%i.%i' or newer required!"
                 % (CONSTANTS.PYTHON_VER_MIN[0], CONSTANTS.PYTHON_VER_MIN[1]))

    # Started with arguments?
    if len(sys.argv) > 1:
        for idx, arg in enumerate(sys.argv):

            # 1st argument is application
            if idx == 0:
                continue

            # Help info
            if arg == "-h" or arg == "--help":
                print("         -h  --help                  Print this help")
                print("         -v  --version               Print version info")
                print("         -c  --config                Use a specific config file")
                print("             --rebuild-cache         Rebuild cache on startup")
                print("             --rebuild-cache-exit    Rebuild cache and exit afterwards")
                print("         -d  --demo                  Demo mode")
                print("             --ignorequit            Don't quit when the 'Q' key is pressed")
                sys.exit(0)

            # Run in a specific mode
            if arg == "--rebuild-cache" or arg == "--rebuild-cache-exit":

                # Clearing the cache
                clear_cache()

                # Rebuild cache only and exit
                if arg == "--rebuild-cache-exit":

                    # Exit when reaching the main loop
                    running = False

            # Run with a specific config file
            if arg == "-c" or arg == "--config" and (idx + 1) < len(sys.argv):
                CONSTANTS.CONFIG_PATH = sys.argv[idx + 1]

            # Display version info
            if arg == "-v" or arg == "--version":
                print("version " + __version__)
                sys.exit(0)

            # Run demo mode
            if arg == "-d" or arg == "--demo":
                CONSTANTS.CONFIG_PATH = CONSTANTS.DEMO_CONFIG_PATH

            # Ignore keyboard 'quit' command
            if arg == "--ignorequit":
                ignore_quit = True

    # Create folder if not exist
    if not os.path.isdir(os.path.dirname(CONSTANTS.APPDATA_DIR)):
        print("Creating config folder '%s'" % CONSTANTS.APPDATA_DIR)
        os.system("mkdir -p %s" % os.path.dirname(CONSTANTS.APPDATA_DIR))

    # Load settings from config file
    CONFIG.load()

    # Signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    LOG.INFO(_LOG_NAME, "Starting camplayer version %s" % __version__)
    LOG.INFO(_LOG_NAME, "Using config file '%s' and cache directory '%s'"
             % (CONSTANTS.CONFIG_PATH, CONSTANTS.CACHE_DIR))

    # Cleanup some stuff in case something went wrong on the previous run
    utils.kill_service('omxplayer.bin', force=True)
    utils.kill_service('vlc', force=True)
    utils.kill_service('pipng', force=True)

    # OMXplayer is absolutely required!
    if not utils.os_package_installed("omxplayer.bin"):
        sys.exit("OMXplayer not installed but required!")

    # ffprobe is absolutely required!
    if not utils.os_package_installed("ffprobe"):
        sys.exit("ffprobe not installed but required!")

    # Get system info
    sys_info = utils.get_system_info()
    gpu_mem = utils.get_gpu_memory()
    hw_info = utils.get_hardware_info()

    # Set some globals for later use
    GLOBALS.PI_SOC          = hw_info.get("soc")    # Not very reliable, usually reports BCM2835
    GLOBALS.PI_MODEL        = hw_info.get("model")
    GLOBALS.PI_SOC_HEVC     = hw_info.get('hevc')
    GLOBALS.NUM_DISPLAYS    = 2 if hw_info.get('dual_hdmi') else 1
    GLOBALS.VLC_SUPPORT     = utils.os_package_installed("vlc")
    GLOBALS.PIPNG_SUPPORT   = utils.os_package_installed("pipng")
    GLOBALS.FFMPEG_SUPPORT  = utils.os_package_installed("ffmpeg")
    GLOBALS.USERNAME        = os.getenv('USER')

    # Log system info
    LOG.INFO(_LOG_NAME, "********************** SYSTEM INFO **********************")
    LOG.INFO(_LOG_NAME, str("Camplayer version             = %s" % __version__))
    LOG.INFO(_LOG_NAME, str("Operating system              = %s" % sys_info))
    LOG.INFO(_LOG_NAME, str("Raspberry Pi SoC              = %s" % hw_info.get("soc")))
    LOG.INFO(_LOG_NAME, str("Raspberry Pi revision         = %s" % hw_info.get("revision")))
    LOG.INFO(_LOG_NAME, str("Raspberry Pi model name       = %s" % hw_info.get("model")))
    LOG.INFO(_LOG_NAME, str("GPU memory allocation         = %i MB" % gpu_mem))
    LOG.INFO(_LOG_NAME, str("Python version                = %s MB" % sys.version.splitlines()[0]))
    LOG.INFO(_LOG_NAME, str("VLC installed                 = %s" % GLOBALS.VLC_SUPPORT))
    LOG.INFO(_LOG_NAME, str("pipng installed               = %s" % GLOBALS.PIPNG_SUPPORT))
    LOG.INFO(_LOG_NAME, str("ffmpeg installed              = %s" % GLOBALS.FFMPEG_SUPPORT))
    LOG.INFO(_LOG_NAME, "*********************************************************")

    # Register for keyboard 'press' events, requires root
    # TODO: check privileges?
    keyboard = InputMonitor(event_type=['press'])

    # Log overwrites for debugging purpose
    for setting in CONFIG.advanced_overwritten:
        LOG.INFO(_LOG_NAME, "advanced setting overwritten for '%s' is '%s'" % (setting[0], setting[1]))

    # Does this system fulfill the minimal requirements
    if CONFIG.HARDWARE_CHECK:
        if not hw_info.get("supported"):
            sys.exit("Unsupported hardware with revision %s ..." % hw_info.get("revision"))

        if gpu_mem < CONSTANTS.MIN_GPU_MEM:
            sys.exit("GPU memory of '%i' MB insufficient ..." % gpu_mem)

    # Auto detect screen resolution
    # For the raspberry pi 4:
    #   both HDMI displays are supposed to have the same configuration
    if CONFIG.SCREEN_HEIGHT == 0 or CONFIG.SCREEN_WIDTH == 0:
        display_conf = utils.get_display_mode()
        CONFIG.SCREEN_HEIGHT = display_conf.get('res_height')
        CONFIG.SCREEN_WIDTH = display_conf.get('res_width')
        LOG.INFO(_LOG_NAME, "Detected screen resolution for HDMI0 is '%ix%i@%iHz'" % (
            CONFIG.SCREEN_WIDTH, CONFIG.SCREEN_HEIGHT, display_conf.get('framerate')))

        if CONFIG.SCREEN_HEIGHT <= 0:
            CONFIG.SCREEN_HEIGHT = 1080
        if CONFIG.SCREEN_WIDTH <= 0:
            CONFIG.SCREEN_WIDTH = 1920

    # Are we sure the 2nd HDMI is on for dual HDMI versions?
    if GLOBALS.NUM_DISPLAYS == 2:
        # Check for resolution instead of display name as the latter one is empty with force HDMI hotplug
        if not utils.get_display_mode(display=7).get('res_height'):
            GLOBALS.NUM_DISPLAYS = 1

    # Calculate the virtual screen size now that we now the physical screen size
    CONSTANTS.VIRT_SCREEN_WIDTH = int(CONFIG.SCREEN_WIDTH * (100 - CONFIG.SCREEN_DOWNSCALE) / 100)
    CONSTANTS.VIRT_SCREEN_HEIGHT = int(CONFIG.SCREEN_HEIGHT * (100 - CONFIG.SCREEN_DOWNSCALE) / 100)
    CONSTANTS.VIRT_SCREEN_OFFSET_X = int((CONFIG.SCREEN_WIDTH - CONSTANTS.VIRT_SCREEN_WIDTH) / 2)
    CONSTANTS.VIRT_SCREEN_OFFSET_Y = int((CONFIG.SCREEN_HEIGHT - CONSTANTS.VIRT_SCREEN_HEIGHT) / 2)
    LOG.INFO(_LOG_NAME, "Using a virtual screen resolution of '%ix%i'" %
             (CONSTANTS.VIRT_SCREEN_WIDTH, CONSTANTS.VIRT_SCREEN_HEIGHT))

    # Workaround: srt subtitles have a maximum display time of 99 hours
    if CONFIG.VIDEO_OSD and (not CONFIG.REFRESHTIME_MINUTES or CONFIG.REFRESHTIME_MINUTES >= 99 * 60):
        CONFIG.REFRESHTIME_MINUTES = 99 * 60
        LOG.WARNING(_LOG_NAME, "Subtitle based OSD enabled, forcing 'refreshtime' to '%i'" % CONFIG.REFRESHTIME_MINUTES)

    # Show 'loading' on master display
    BackGroundManager.show_icon_instant(BackGround.LOADING, display_idx=0)

    # Initialize screens and windows
    screenmanager = ScreenManager()
    if screenmanager.valid_screens < 1:
        sys.exit("No valid screen configuration found, check your config file!")

    # Hide 'loading' message on master display
    BackGroundManager.hide_icon_instant(display_idx=0)

    # Working loop
    while running:

        # Trigger screenmanager working loop
        screenmanager.do_work()

        for event in keyboard.get_events():
            last_added = time.monotonic()

            if event.code in KEYCODE.KEY_NUM.keys():
                LOG.DEBUG(_LOG_NAME, "Numeric key event: %i" % KEYCODE.KEY_NUM.get(event.code))

                num_array.append(KEYCODE.KEY_NUM.get(event.code))

                # Two digit for numbers from 0 -> 99
                if len(num_array) > 2:
                    num_array.pop(0)
            else:

                # Non numeric key, clear numeric num_array
                num_array.clear()

                if event.code == KEYCODE.KEY_RIGHT:
                    screenmanager.on_action(Action.SWITCH_NEXT)

                elif event.code == KEYCODE.KEY_LEFT:
                    screenmanager.on_action(Action.SWITCH_PREV)

                elif event.code == KEYCODE.KEY_UP:
                    screenmanager.on_action(Action.SWITCH_QUALITY_UP)

                elif event.code == KEYCODE.KEY_DOWN:
                    screenmanager.on_action(Action.SWITCH_QUALITY_DOWN)

                elif event.code == KEYCODE.KEY_ENTER or event.code == KEYCODE.KEY_KPENTER:
                    screenmanager.on_action(Action.SWITCH_SINGLE, 0)

                elif event.code == KEYCODE.KEY_ESC or event.code == KEYCODE.KEY_EXIT:
                    screenmanager.on_action(Action.SWITCH_GRID)

                elif event.code == KEYCODE.KEY_SPACE:
                    screenmanager.on_action(Action.SWITCH_PAUSE_UNPAUSE)

                elif event.code == KEYCODE.KEY_D:
                    screenmanager.on_action(Action.SWITCH_DISPLAY_CONTROL)

                elif event.code == KEYCODE.KEY_Q and not ignore_quit:
                    running = False

                break

        # Timeout between key presses expired?
        if time.monotonic() > (last_added + (CONSTANTS.KEY_TIMEOUT_MS / 1000)):
            num_array.clear()

        # 1 second delay to accept multiple digit numbers
        elif time.monotonic() > (last_added + (CONSTANTS.KEY_MULTIDIGIT_MS / 1000)) and len(num_array) > 0:

            LOG.INFO(_LOG_NAME, "Process numeric key input '%s'" % str(num_array))

            number = 0
            number += num_array[-2] * 10 if len(num_array) > 1 else 0
            number += num_array[-1]

            if number == 0:
                num_array.clear()
                screenmanager.on_action(Action.SWITCH_GRID)
            else:
                num_array.clear()
                screenmanager.on_action(Action.SWITCH_SINGLE, number - 1)

        time.sleep(0.1)

    # Cleanup stuff before exit
    keyboard.destroy()
    BackGroundManager.destroy()
    utils.kill_service('omxplayer.bin', force=True)
    utils.kill_service('vlc', force=True)
    utils.kill_service('pipng', force=True)

    LOG.INFO(_LOG_NAME, "Exiting raspberry pi camplayer, have a nice day!")
    sys.exit(0)


if __name__ == "__main__":
    main()