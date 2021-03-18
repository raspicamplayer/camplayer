#!/usr/bin/python3

import subprocess
import time
import os

from utils.logger import LOG
from utils.settings import BACKGROUND, CONFIG
from utils.constants import CONSTANTS
from utils.globals import GLOBALS


class BackGround(object):

    # Overlays in front of video
    LOADING     = "icon_loading.png"
    PAUSED      = "icon_paused.png"
    CONTROL     = "icon_control.png"

    # Backgrounds behind video
    NOLINK_1X1  = "nolink_1x1.png"
    NOLINK_2X2  = "nolink_2x2.png"
    NOLINK_3X3  = "nolink_3x3.png"
    NOLINK_4X4  = "nolink_4x4.png"
    NOLINK_1P5  = "nolink_1P5.png"
    NOLINK_1P7  = "nolink_1P7.png"
    NOLINK_1P12 = "nolink_1P12.png"
    NOLINK_2P8  = "nolink_2P8.png"
    NOLINK_3P4  = "nolink_3P4.png"

    @classmethod
    def NOLINK(cls, window_count):
        """Get NO LINK image background based on window count"""

        _map = ({
            1: cls.NOLINK_1X1,
            3: cls.NOLINK_1X1,
            4: cls.NOLINK_2X2,
            6: cls.NOLINK_1P5,
            7: cls.NOLINK_3P4,
            8: cls.NOLINK_1P7,
            9: cls.NOLINK_3X3,
            10: cls.NOLINK_2P8,
            13: cls.NOLINK_1P12,
            16: cls.NOLINK_4X4
        })

        file_path = str("%s%s_%i_%i.png" % (CONSTANTS.CACHE_DIR, _map.get(window_count).split('.png')[0],
                                            CONSTANTS.VIRT_SCREEN_WIDTH, CONSTANTS.VIRT_SCREEN_HEIGHT))

        if os.path.isfile(file_path):
            return file_path

        if BackGroundManager.scale_background(
                src_path=CONSTANTS.RESOURCE_DIR_BCKGRND + _map.get(window_count), dest_path=file_path,
                dest_width=CONSTANTS.VIRT_SCREEN_WIDTH, dest_height=CONSTANTS.VIRT_SCREEN_HEIGHT):
            return file_path

        return ""


class BackGroundManager(object):

    _MODULE = "BackGroundManager"

    _proc_icons         = [None for _ in range(GLOBALS.NUM_DISPLAYS)]
    _proc_instant_icon  = [None for _ in range(GLOBALS.NUM_DISPLAYS)]
    _proc_background    = [None for _ in range(GLOBALS.NUM_DISPLAYS)]
    _icons              = [[] for _ in range(GLOBALS.NUM_DISPLAYS)]
    _backgrounds        = [[] for _ in range(GLOBALS.NUM_DISPLAYS)]

    active_icon         = ["" for _ in range(GLOBALS.NUM_DISPLAYS)]
    active_icon_display = ["" for _ in range(GLOBALS.NUM_DISPLAYS)]
    active_background   = ["" for _ in range(GLOBALS.NUM_DISPLAYS)]

    _background_layer = -100    # Must be higher than -127 to hide the framebuffer
    _foreground_layer = 1000    # Must be higher than the OMXplayer layers

    @classmethod
    def show_icon_instant(cls, filename, display_idx=0):
        """Show png icon in front of video immediately"""

        if not CONFIG.ENABLE_ICONS or not GLOBALS.PIPNG_SUPPORT:
            return

        display_idx = 1 if display_idx == 1 else 0

        cls.hide_icon_instant(display_idx)

        pngview_cmd = ["pipng",
                "-b", "0",                                  # No 2nd background layer under image
                "-l", str(cls._foreground_layer + 1),       # Set layer number
                "-d", "2" if display_idx == 0 else "7",     # Set display number
                "-x", str(CONSTANTS.ICON_OFFSET_X),         # 60px offset x-axis
                "-y", str(CONSTANTS.ICON_OFFSET_Y),         # 60px offset y-axis
                "-n",                                       # Non interactive mode
                "-h",                                       # Hide lower layers
                str(CONSTANTS.RESOURCE_DIR_ICONS + filename)
            ]

        cls._proc_instant_icon[display_idx] = \
            subprocess.Popen(pngview_cmd, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    @classmethod
    def hide_icon_instant(cls, display_idx=0):
        """Hide icon loaded with the instant method"""

        if not CONFIG.ENABLE_ICONS or not GLOBALS.PIPNG_SUPPORT:
            return

        display_idx = 1 if display_idx == 1 else 0

        if cls._proc_instant_icon[display_idx]:
            cls._proc_instant_icon[display_idx].terminate()
            cls._proc_instant_icon[display_idx] = None

    @classmethod
    def add_icon(cls, filename, display_idx=0):
        """Add icon to pipng queue"""

        display_idx = 1 if display_idx == 1 else 0

        # Already present? -> ignore
        for image in cls._icons[display_idx]:
            if image == filename:
                return

        cls._icons[display_idx].append(filename)

    @classmethod
    def add_background(cls, window_count=1, display_idx=0):
        """Add background to pipng queue"""

        display_idx = 1 if display_idx == 1 else 0

        file_path = BackGround.NOLINK(window_count=window_count)

        if not file_path:
            return

        # Already present? -> ignore
        for image in cls._backgrounds[display_idx]:
            if image == file_path:
                return

        cls._backgrounds[display_idx].append(file_path)

    @classmethod
    def load_backgrounds(cls):
        """Load pipng background queue"""

        if CONFIG.BACKGROUND_MODE == BACKGROUND.OFF or not GLOBALS.PIPNG_SUPPORT:
            return

        if CONFIG.BACKGROUND_MODE == BACKGROUND.HIDE_FRAMEBUFFER:

            for display_idx in range(GLOBALS.NUM_DISPLAYS):

                if len(cls._backgrounds[display_idx]) <= 0:
                    continue

                subprocess.Popen(["pipng", "-b", "000F", "-n", "-d", "2" if display_idx == 0 else "7"],
                    shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

        else:

            static_background = CONFIG.BACKGROUND_MODE == BACKGROUND.STATIC

            for display_idx in range(GLOBALS.NUM_DISPLAYS):

                if len(cls._backgrounds[display_idx]) <= 0:
                    continue

                pngview_cmd = ["pipng",
                    "-b", "0",                                  # No 2nd background layer under image
                    "-l", str(cls._background_layer),           # Set layer number
                    "-d", "2" if display_idx == 0 else "7",     # Set display number
                    "-h",                                       # Hide lower layers (less GPU performance impact)
                ]

                if not static_background:
                    pngview_cmd.append("-i")                    # Start with all images invisible

                # Add all background images, currently limited to 10
                for image in cls._backgrounds[display_idx]:
                    pngview_cmd.append(image)

                    # TODO: find best match with static backgrounds and multiple screens
                    if static_background:
                        break

                LOG.DEBUG(cls._MODULE, "Loading pipng for display '%i' with command '%s'" %
                    (display_idx + 1, pngview_cmd))

                cls._proc_background[display_idx] = \
                    subprocess.Popen(pngview_cmd, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    @classmethod
    def load_icons(cls):
        """Load pipng icon queue"""

        if not CONFIG.ENABLE_ICONS or not GLOBALS.PIPNG_SUPPORT:
            return

        for display_idx in range(GLOBALS.NUM_DISPLAYS):

            if len(cls._icons[display_idx]) <= 0:
                continue

            pngview_cmd = ["pipng",
                "-b", "0",                                  # No 2nd background layer under image
                "-l", str(cls._foreground_layer),           # Set layer number
                "-d", "2" if display_idx == 0 else "7",     # Set display number
                "-i",                                       # Start with all images invisible
                "-x", str(CONSTANTS.ICON_OFFSET_X),         # 60px offset x-axis
                "-y", str(CONSTANTS.ICON_OFFSET_Y),         # 60px offset y-axis
            ]

            # Add all images, currently limited to 10
            for image in cls._icons[display_idx]:
                pngview_cmd.append(CONSTANTS.RESOURCE_DIR_ICONS + image)

            LOG.DEBUG(cls._MODULE, "Loading pipng for display '%i' with command '%s'" %
                (display_idx, pngview_cmd))

            cls._proc_icons[display_idx] = \
                subprocess.Popen(pngview_cmd, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    @classmethod
    def show_icon(cls, filename, display_idx=0):
        """Show pipng icon from queue"""

        if not CONFIG.ENABLE_ICONS or not GLOBALS.PIPNG_SUPPORT:
            return

        display_idx = 1 if display_idx == 1 else 0

        # Show new image/icon
        for idx, image in enumerate(cls._icons[display_idx]):
            if filename == image:
                LOG.DEBUG(cls._MODULE, "setting icon '%s' visible for display '%i" % (filename, display_idx))
                cls._proc_icons[display_idx].stdin.write(str(idx).encode('utf-8'))
                cls._proc_icons[display_idx].stdin.flush()

        cls.active_icon[display_idx] = filename

    @classmethod
    def hide_icon(cls, display_idx=0):
        """Hide active pipng iconn"""

        if not CONFIG.ENABLE_ICONS or not GLOBALS.PIPNG_SUPPORT:
            return

        display_idx = 1 if display_idx == 1 else 0

        if not cls.active_icon[display_idx]:
            return

        LOG.DEBUG(cls._MODULE, "hiding icon '%s' for display '%i" % (cls.active_icon[display_idx], display_idx))

        cls._proc_icons[display_idx].stdin.write("i".encode('utf-8'))
        cls._proc_icons[display_idx].stdin.flush()

        cls.active_icon[display_idx] = ""

        # pipng needs some milliseconds to read stdin
        # Especially important when hide_icon() will be immediately followed by show_icon()
        time.sleep(0.025)

    @classmethod
    def show_background(cls, filename, display_idx=0):
        """Show pipng background from queue"""

        if CONFIG.BACKGROUND_MODE != BACKGROUND.DYNAMIC or not GLOBALS.PIPNG_SUPPORT:
            return

        display_idx = 1 if display_idx == 1 else 0

        if cls.active_background[display_idx] == filename:
            return

        # Show new image/icon
        for idx, image in enumerate(cls._backgrounds[display_idx]):
            if filename == image:
                LOG.DEBUG(cls._MODULE, "setting background '%s' visible for display '%i" % (filename, display_idx))
                cls._proc_background[display_idx].stdin.write(str(idx).encode('utf-8'))
                cls._proc_background[display_idx].stdin.flush()

        cls.active_background[display_idx] = filename

    @classmethod
    def scale_background(cls, src_path, dest_path, dest_width, dest_height):
        """Scale background image to the requested width and height"""

        if not GLOBALS.FFMPEG_SUPPORT:
            return False

        ffmpeg_cmd = str("ffmpeg -i '%s' -vf scale=%i:%i '%s'" % (src_path, dest_width, dest_height, dest_path))

        try:
            subprocess.check_output(ffmpeg_cmd, shell=True, stderr=subprocess.STDOUT, timeout=5)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            LOG.ERROR(cls._MODULE, "Scaling background image '%s' failed" % src_path)

        if os.path.isfile(dest_path):
            return True

        return False

    @classmethod
    def destroy(cls):
        """Destroy pipng instances"""

        if not GLOBALS.PIPNG_SUPPORT:
            return

        if CONFIG.ENABLE_ICONS:
            for display_idx in range(GLOBALS.NUM_DISPLAYS):
                if cls._proc_icons[display_idx]:
                    cls._proc_icons[display_idx].stdin.write("c".encode('utf-8'))

        if CONFIG.BACKGROUND_MODE == BACKGROUND.DYNAMIC:
            for display_idx in range(GLOBALS.NUM_DISPLAYS):
                if cls._proc_background[display_idx]:
                    cls._proc_background[display_idx].stdin.write("c".encode('utf-8'))
